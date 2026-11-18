using AGUI.Server;
using Desk.AgentFramework;
using Desk.Core;
using Microsoft.Agents.AI;
using Microsoft.Agents.AI.Hosting.AGUI.AspNetCore;
using Microsoft.Extensions.AI;

WebApplicationBuilder builder = WebApplication.CreateBuilder(args);

builder.Services.AddAGUIServer();
builder.Services.AddSingleton<OrderBook>();
builder.Services.AddSingleton<Ledger>();
builder.Services.AddSingleton(new WireLog(builder.Configuration["DESK_WIRE_LOG"]));

WebApplication app = builder.Build();
app.UseMiddleware<WireTap>();

OrderBook orders = app.Services.GetRequiredService<OrderBook>();
Ledger ledger = app.Services.GetRequiredService<Ledger>();

// The same model stand-in and the same three tools as the hand-built service. The agent type runs the
// tool loop itself, so there is no UseFunctionInvocation() here.
IChatClient model = new ScriptedModel(orders, TimeSpan.FromMilliseconds(app.Configuration.GetValue("DESK_WORD_DELAY_MS", 15)));
AIAgent desk = model.AsAIAgent(tools: new DeskTools(orders, ledger).Create());
AIAgent agent = new CaseStateAgent(desk);

// One call maps the endpoint: request binding, the event stream, interrupts and resume.
app.MapAGUIServer("/agent", agent)
    .WithMetadata(new AGUIStreamOptions().MapResultAsStateSnapshot(DeskTools.DraftReplyName));

// For the lab only: what the payment stand-in holds, and a way to empty it between runs.
app.MapGet("/ledger", () => Results.Json(new { attempts = ledger.Attempts, refunds = ledger.Refunds }));
app.MapPost("/reset", (WireLog wire) =>
{
    ledger.Clear();
    wire.Clear();
    return Results.NoContent();
});

await app.RunAsync();
