using AGUI.Server;
using Desk.AgentFramework;
using Desk.Core;
using Microsoft.Agents.AI;
using Microsoft.Agents.AI.Hosting;
using Microsoft.Agents.AI.Hosting.AGUI.AspNetCore;
using Microsoft.Extensions.AI;

WebApplicationBuilder builder = WebApplication.CreateBuilder(args);

builder.Services.AddAGUIServer();
builder.Services.AddSingleton<OrderBook>();
builder.Services.AddSingleton<Ledger>();
builder.Services.AddSingleton(new WireLog(builder.Configuration["DESK_WIRE_LOG"]));

builder.Services.AddSingleton<ModelCalls>();

// The same model stand-in and the same three tools as the hand-built service. The agent type runs the
// tool loop itself, so there is no UseFunctionInvocation() here.
IHostedAgentBuilder desk = builder.Services.AddAIAgent("desk", (services, name) =>
{
    IConfiguration settings = services.GetRequiredService<IConfiguration>();
    OrderBook orders = services.GetRequiredService<OrderBook>();
    IChatClient model = new SeenByModel(
        new ScriptedModel(orders, TimeSpan.FromMilliseconds(settings.GetValue("DESK_WORD_DELAY_MS", 15))),
        services.GetRequiredService<ModelCalls>());
    ChatClientAgentOptions options = new()
    {
        Name = name,
        ChatOptions = new ChatOptions { Tools = new DeskTools(orders, services.GetRequiredService<Ledger>()).Create() },
        DisableApprovalResponseBinding = !settings.GetValue("DESK_VERIFY_RESUME", true),
    };
    AIAgent agent = model.AsAIAgent(options);
    if (settings.GetValue("DESK_DROP_ECHO", true))
    {
        agent = new DropEchoedRequestsAgent(agent);
    }

    return new CaseStateAgent(agent);
});

desk.WithSessionStore(
    (services, _) => services.GetRequiredService<IConfiguration>()["DESK_SESSIONS"] == "none" ? new NoopAgentSessionStore() : new InMemoryAgentSessionStore(),
    withIsolation: false);

WebApplication app = builder.Build();
app.UseMiddleware<WireTap>();

// One call maps the endpoint: request binding, the event stream, interrupts and resume.
app.MapAGUIServer(desk, "/agent")
    .WithMetadata(new AGUIStreamOptions().MapResultAsStateSnapshot(DeskTools.DraftReplyName));

// For the lab only: what the payment stand-in holds, and a way to empty it between runs.
app.MapGet("/ledger", (Ledger ledger) => Results.Json(new { attempts = ledger.Attempts, refunds = ledger.Refunds }));
app.MapPost("/reset", (Ledger ledger, WireLog wire, ModelCalls calls) =>
{
    ledger.Clear();
    wire.Clear();
    calls.Clear();
    return Results.NoContent();
});

await app.RunAsync();
