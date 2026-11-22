using System.Security.Claims;
using System.Text;
using System.Text.Json;
using AGUI.Abstractions;
using AGUI.Server;
using Desk.Agent;
using Desk.Core;
using Microsoft.AspNetCore.Authentication.JwtBearer;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Extensions.AI;
using Microsoft.Extensions.Options;
using Microsoft.IdentityModel.Tokens;
using JsonOptions = Microsoft.AspNetCore.Http.Json.JsonOptions;

WebApplicationBuilder builder = WebApplication.CreateBuilder(args);

builder.Services.Configure<JsonOptions>(options =>
{
    options.SerializerOptions.TypeInfoResolverChain.Add(AIJsonUtilities.DefaultOptions.TypeInfoResolver!);
    options.SerializerOptions.TypeInfoResolverChain.Add(AGUIJsonSerializerContext.Default);
    AGUIJsonUtilities.RegisterInterruptContentTypes(options.SerializerOptions);
});

// Every request needs a token made for this service. In the lab the web host signs it with a shared fake
// key; with a real identity provider, set Authority and Audience here and delete the key.
builder.Services.AddAuthentication(JwtBearerDefaults.AuthenticationScheme).AddJwtBearer(options =>
{
    options.MapInboundClaims = false;
    options.TokenValidationParameters = new TokenValidationParameters
    {
        ValidIssuer = LabTokenIssuer.Issuer,
        ValidAudience = LabTokenIssuer.Audience,
        IssuerSigningKey = new SymmetricSecurityKey(Encoding.UTF8.GetBytes(builder.Configuration["DESK_TOKEN_KEY"] ?? LabTokenIssuer.FakeKey)),
        ValidAlgorithms = [SecurityAlgorithms.HmacSha256],
        NameClaimType = "name",
        RoleClaimType = "roles",
        ClockSkew = TimeSpan.FromSeconds(builder.Configuration.GetValue("DESK_CLOCK_SKEW_SECONDS", 30)),
    };
});
builder.Services.AddAuthorizationBuilder()
    .AddPolicy(Callers.Policy, policy => policy.RequireAuthenticatedUser().RequireRole("agent", "supervisor"));

builder.Services.AddHttpContextAccessor();
builder.Services.AddSingleton<OrderBook>();
builder.Services.AddSingleton<Ledger>();
builder.Services.AddSingleton(new WireLog(builder.Configuration["DESK_WIRE_LOG"]));
builder.Services.AddSingleton(TimeProvider.System);
builder.Services.AddSingleton<PendingApprovals>();

// The tools ask who the caller is at the moment they run. The answer comes from the request's
// validated token; the model has no way to supply it.
builder.Services.AddSingleton<IChatClient>(services =>
{
    IHttpContextAccessor http = services.GetRequiredService<IHttpContextAccessor>();
    return DeskAgent.Create(
        services.GetRequiredService<OrderBook>(),
        services.GetRequiredService<Ledger>(),
        TimeSpan.FromMilliseconds(builder.Configuration.GetValue("DESK_WORD_DELAY_MS", 15)),
        () => Callers.From(http.HttpContext?.User));
});

WebApplication app = builder.Build();

bool verifyResume = app.Configuration.GetValue("DESK_VERIFY_RESUME", true);

app.UseAuthentication();
app.UseAuthorization();

app.MapPost("/agent", (
    [FromBody] RunAgentInput input,
    ClaimsPrincipal user,
    IOptions<JsonOptions> jsonOptions,
    IChatClient agent,
    WireLog wire,
    PendingApprovals approvals,
    CancellationToken cancellationToken) =>
{
    JsonSerializerOptions json = jsonOptions.Value.SerializerOptions;
    Caller caller = Callers.From(user);

    // An approval is accepted only from the person it was asked of, and only for the call this server proposed.
    if (verifyResume && approvals.Redeem(input.Resume, caller.Subject) is { } refusal)
    {
        return Results.Problem(refusal.Detail, statusCode: refusal.Status, title: "Approval refused");
    }

    AGUIStreamOptions stream = new AGUIStreamOptions().MapResultAsStateSnapshot(DeskTools.DraftReplyName);
    ChatRequestContext context = input.ToChatRequestContext(json, stream);
    if (input.State is { ValueKind: JsonValueKind.Object } state)
    {
        context.Messages.Insert(0, new ChatMessage(ChatRole.System, ScriptedModel.StatePrefix + state.GetRawText()));
    }

    IAsyncEnumerable<ChatResponseUpdate> updates = agent.GetStreamingResponseAsync(context.Messages, context.ChatOptions, cancellationToken);
    IAsyncEnumerable<BaseEvent> events = approvals.WatchAsync(updates.AsAGUIEventStreamAsync(context, cancellationToken), caller.Subject, cancellationToken);
    return new EventStreamResult(wire.RecordAsync(input, WithoutRawEvents(events, cancellationToken), json, cancellationToken));
}).RequireAuthorization(Callers.Policy);

// For the lab only, and only when asked for: what the payment stand-in holds, and a way to empty it.
if (app.Configuration.GetValue("DESK_LAB", false))
{
    app.MapGet("/ledger", (Ledger ledger) => Results.Json(new { attempts = ledger.Attempts, refunds = ledger.Refunds }));
    app.MapGet("/wire", (WireLog wire) => Results.Json(wire.Entries.Select(entry => new { events = entry.Events.Count, last = entry.Events.LastOrDefault(), completed = entry.Completed })));
    app.MapPost("/reset", (Ledger ledger, WireLog wire) =>
    {
        ledger.Clear();
        wire.Clear();
        return Results.NoContent();
    });
}

await app.RunAsync();

static async IAsyncEnumerable<BaseEvent> WithoutRawEvents(IAsyncEnumerable<BaseEvent> events, [System.Runtime.CompilerServices.EnumeratorCancellation] CancellationToken cancellationToken)
{
    await foreach (BaseEvent item in events.WithCancellation(cancellationToken))
    {
        item.RawEvent = null;
        yield return item;
    }
}
