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
builder.Services.AddSingleton<IChatClient>(services => DeskAgent.Create(
    services.GetRequiredService<OrderBook>(),
    services.GetRequiredService<Ledger>(),
    TimeSpan.FromMilliseconds(builder.Configuration.GetValue("DESK_WORD_DELAY_MS", 15))));

WebApplication app = builder.Build();

app.MapPost("/agent", (
    [FromBody] RunAgentInput input,
    IOptions<JsonOptions> jsonOptions,
    IChatClient agent,
    WireLog wire,
    CancellationToken cancellationToken) =>
{
    JsonSerializerOptions json = jsonOptions.Value.SerializerOptions;

    // The result of draft_reply is the new shared state, so it goes out as a STATE_SNAPSHOT event.
    AGUIStreamOptions stream = new AGUIStreamOptions().MapResultAsStateSnapshot(DeskTools.DraftReplyName);
    ChatRequestContext context = input.ToChatRequestContext(json, stream);

    // State the browser sent comes back to the model as part of the conversation.
    if (input.State is { ValueKind: JsonValueKind.Object } state)
    {
        context.Messages.Insert(0, new ChatMessage(ChatRole.System, ScriptedModel.StatePrefix + state.GetRawText()));
    }

    IAsyncEnumerable<ChatResponseUpdate> updates = agent.GetStreamingResponseAsync(context.Messages, context.ChatOptions, cancellationToken);
    IAsyncEnumerable<BaseEvent> events = updates.AsAGUIEventStreamAsync(context, cancellationToken);
    return new EventStreamResult(wire.RecordAsync(input, events, json, cancellationToken));
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
