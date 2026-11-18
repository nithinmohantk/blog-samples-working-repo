using System.Text.Json;
using AGUI.Abstractions;
using AGUI.Server;
using Desk.Agent;
using Desk.Core;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Extensions.AI;
using Microsoft.Extensions.Options;
using JsonOptions = Microsoft.AspNetCore.Http.Json.JsonOptions;

WebApplicationBuilder builder = WebApplication.CreateBuilder(args);

// The protocol types come with source-generated JSON metadata. Without these three lines the
// request body does not bind.
builder.Services.Configure<JsonOptions>(options =>
{
    options.SerializerOptions.TypeInfoResolverChain.Add(AIJsonUtilities.DefaultOptions.TypeInfoResolver!);
    options.SerializerOptions.TypeInfoResolverChain.Add(AGUIJsonSerializerContext.Default);
    AGUIJsonUtilities.RegisterInterruptContentTypes(options.SerializerOptions);
});

builder.Services.AddSingleton<OrderBook>();
builder.Services.AddSingleton<Ledger>();
builder.Services.AddSingleton<WireLog>();
builder.Services.AddSingleton(TimeProvider.System);
builder.Services.AddSingleton<PendingApprovals>();
builder.Services.AddSingleton<IChatClient>(services => DeskAgent.Create(
    services.GetRequiredService<OrderBook>(),
    services.GetRequiredService<Ledger>(),
    TimeSpan.FromMilliseconds(builder.Configuration.GetValue("DESK_WORD_DELAY_MS", 15))));

WebApplication app = builder.Build();

// Both default to the safe choice. The lab turns them off to measure what they change.
bool verifyResume = app.Configuration.GetValue("DESK_VERIFY_RESUME", true);
bool rawEvents = app.Configuration.GetValue("DESK_RAW_EVENTS", false);

app.MapPost("/agent", (
    [FromBody] RunAgentInput input,
    IOptions<JsonOptions> jsonOptions,
    IChatClient agent,
    WireLog wire,
    PendingApprovals approvals,
    CancellationToken cancellationToken) =>
{
    JsonSerializerOptions json = jsonOptions.Value.SerializerOptions;

    // An approval arrives as a "resume" entry that also carries the tool call to run. Accept it only
    // if this server proposed exactly that call and it has not been answered yet.
    if (verifyResume && !approvals.TryRedeem(input.Resume, out string problem))
    {
        return Results.Problem(problem, statusCode: StatusCodes.Status409Conflict, title: "Approval refused");
    }

    // The result of draft_reply is the new shared state, so it goes out as a STATE_SNAPSHOT event.
    AGUIStreamOptions stream = new AGUIStreamOptions().MapResultAsStateSnapshot(DeskTools.DraftReplyName);
    ChatRequestContext context = input.ToChatRequestContext(json, stream);

    // State the browser sent comes back to the model as part of the conversation.
    if (input.State is { ValueKind: JsonValueKind.Object } state)
    {
        context.Messages.Insert(0, new ChatMessage(ChatRole.System, ScriptedModel.StatePrefix + state.GetRawText()));
    }

    IAsyncEnumerable<ChatResponseUpdate> updates = agent.GetStreamingResponseAsync(context.Messages, context.ChatOptions, cancellationToken);
    IAsyncEnumerable<BaseEvent> events = approvals.WatchAsync(updates.AsAGUIEventStreamAsync(context, cancellationToken), cancellationToken);
    return new EventStreamResult(wire.RecordAsync(input, rawEvents ? events : WithoutRawEvents(events, cancellationToken), json, cancellationToken));
});

// For the lab only: what the payment stand-in holds, and a way to empty it between runs.
app.MapGet("/ledger", (Ledger ledger) => Results.Json(new { attempts = ledger.Attempts, refunds = ledger.Refunds }));
app.MapPost("/reset", (Ledger ledger, WireLog wire) =>
{
    ledger.Clear();
    wire.Clear();
    return Results.NoContent();
});

await app.RunAsync();

// Each event can carry the whole model update it was made from in "rawEvent". The UI does not need it,
// it multiplies the size of the stream, and it shows internal structure to whoever reads the response.
static async IAsyncEnumerable<BaseEvent> WithoutRawEvents(IAsyncEnumerable<BaseEvent> events, [System.Runtime.CompilerServices.EnumeratorCancellation] CancellationToken cancellationToken)
{
    await foreach (BaseEvent item in events.WithCancellation(cancellationToken))
    {
        item.RawEvent = null;
        yield return item;
    }
}
