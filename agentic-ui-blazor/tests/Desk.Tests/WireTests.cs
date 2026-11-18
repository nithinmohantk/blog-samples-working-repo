using System.Net;
using System.Text;
using System.Text.Json;
using AGUI.Abstractions;
using AGUI.Client;
using Desk.Agent;
using Desk.Core;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.Extensions.AI;
using Microsoft.Extensions.DependencyInjection;
using Xunit;

namespace Desk.Tests;

/// <summary>
/// Layer 2: the agent service over AG-UI. A real client talks to the real endpoint on an in-memory
/// server, and the tests read what crossed the wire. Each trace is also written out for the article.
/// </summary>
public sealed class WireTests : IClassFixture<WebApplicationFactory<WireLog>>
{
    private readonly WebApplicationFactory<WireLog> _factory;
    private readonly HttpClient _http;
    private readonly IChatClient _chat;
    private readonly WireLog _wire;
    private readonly Ledger _ledger;

    public WireTests(WebApplicationFactory<WireLog> factory)
    {
        _factory = factory.WithWebHostBuilder(host => host.UseSetting("DESK_WORD_DELAY_MS", "0"));
        _http = _factory.CreateClient();
        _chat = new AGUIChatClient(new AGUIChatClientOptions(_http, "/agent"));
        _wire = _factory.Services.GetRequiredService<WireLog>();
        _ledger = _factory.Services.GetRequiredService<Ledger>();
        _wire.Clear();
        _ledger.Clear();
    }

    [Fact]
    public async Task Text_is_a_run_with_one_message_in_it()
    {
        await RunAsync([new(ChatRole.User, "hello")]);

        WireEntry entry = Assert.Single(_wire.Entries);
        Trace.Write("text", _wire.Entries);
        Assert.Equal("RUN_STARTED", entry.Events[0]);
        Assert.Equal("RUN_FINISHED", entry.Events[^1]);
        Assert.Contains("TEXT_MESSAGE_CONTENT", entry.Events);
    }

    [Fact]
    public async Task A_backend_tool_shows_its_call_and_its_result()
    {
        List<ChatResponseUpdate> updates = await RunAsync([new(ChatRole.User, "Where is order O-1001?")]);

        Trace.Write("backend tool", _wire.Entries);
        WireEntry entry = Assert.Single(_wire.Entries);
        Assert.Contains("TOOL_CALL_START", entry.Events);
        Assert.Contains("TOOL_CALL_RESULT", entry.Events);
        Assert.Contains(updates.SelectMany(u => u.Contents).OfType<FunctionResultContent>(), r => r.Result?.ToString()?.Contains("Synthetic kettle") == true);
    }

    [Theory]
    [InlineData(true, 1)]
    [InlineData(false, 0)]
    public async Task An_approval_is_two_runs_and_money_moves_only_in_the_second(bool approved, int refunds)
    {
        List<ChatMessage> messages = [new(ChatRole.User, "Refund order O-1003")];
        List<ChatResponseUpdate> first = await RunAsync(messages);
        ToolApprovalRequestContent request = first.SelectMany(u => u.Contents).OfType<ToolApprovalRequestContent>().Single();
        Assert.Equal(0, _ledger.Attempts);

        messages.Add(new(ChatRole.Assistant, [request]));
        messages.Add(new(ChatRole.User, [request.CreateResponse(approved)]));
        List<ChatResponseUpdate> second = await RunAsync(messages);

        Trace.Write(approved ? "approval, approved" : "approval, rejected", _wire.Entries);
        Assert.Equal(2, _wire.Entries.Count);
        Assert.Equal(refunds, _ledger.Refunds.Count);
        Assert.Contains(approved ? "recorded" : "No refund was made", string.Concat(second.Select(u => u.Text)));
    }

    [Fact]
    public async Task Sending_the_same_approval_twice_pays_once()
    {
        List<ChatMessage> messages = [new(ChatRole.User, "Refund order O-1003")];
        ToolApprovalRequestContent request = (await RunAsync(messages)).SelectMany(u => u.Contents).OfType<ToolApprovalRequestContent>().Single();
        messages.Add(new(ChatRole.Assistant, [request]));
        messages.Add(new(ChatRole.User, [request.CreateResponse(true)]));

        await RunAsync(messages);
        List<ChatResponseUpdate> replay = await RunAsync(messages);

        Assert.Single(_ledger.Refunds);
        Assert.Equal(2, _ledger.Attempts);
        Assert.Contains("refunded earlier", string.Concat(replay.Select(u => u.Text)));
    }

    [Fact]
    public async Task State_goes_out_as_a_snapshot_and_comes_back_in_the_next_request()
    {
        List<ChatResponseUpdate> first = await RunAsync([new(ChatRole.User, "Draft a reply for order O-1001")]);
        Assert.Contains(first, u => u.RawRepresentation is StateSnapshotEvent);

        ChatOptions withState = new()
        {
            RawRepresentationFactory = _ => new RunAgentInput { State = JsonSerializer.SerializeToElement(new { signature = "Sam, Order Desk" }) },
        };
        List<ChatResponseUpdate> second = await RunAsync([new(ChatRole.User, "Draft a formal reply for order O-1001")], withState);

        Trace.Write("shared state", _wire.Entries);
        StateSnapshotEvent snapshot = second.Select(u => u.RawRepresentation).OfType<StateSnapshotEvent>().Single();
        Assert.EndsWith("Regards, Sam, Order Desk", snapshot.Snapshot.GetProperty("reply").GetString());
        Assert.Equal("formal", snapshot.Snapshot.GetProperty("tone").GetString());
    }

    [Fact]
    public async Task Stopping_the_client_stops_the_run_on_the_server()
    {
        using CancellationTokenSource stop = new();
        int seen = 0;
        await Assert.ThrowsAnyAsync<OperationCanceledException>(async () =>
        {
            await foreach (ChatResponseUpdate update in _chat.GetStreamingResponseAsync([new(ChatRole.User, "Explain the refund policy")], cancellationToken: stop.Token))
            {
                if (update.Text.Length > 0 && ++seen == 3)
                {
                    stop.Cancel();
                }
            }
        });

        // The server notices on its next write. Give it a moment, then read what it recorded.
        for (int i = 0; i < 100 && _wire.Entries.Count == 0; i++)
        {
            await Task.Delay(50);
        }

        Trace.Write("cancelled", _wire.Entries);
        WireEntry entry = Assert.Single(_wire.Entries);
        Assert.False(entry.Completed);
        Assert.DoesNotContain("RUN_FINISHED", entry.Events);
    }

    [Fact]
    public async Task A_body_that_is_not_a_run_request_is_refused()
    {
        using HttpResponseMessage response = await _http.PostAsync("/agent", new StringContent("{\"messages\": 5}", Encoding.UTF8, "application/json"));
        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
        Assert.Empty(_wire.Entries);
    }

    private async Task<List<ChatResponseUpdate>> RunAsync(List<ChatMessage> messages, ChatOptions? options = null)
    {
        List<ChatResponseUpdate> updates = [];
        await foreach (ChatResponseUpdate update in _chat.GetStreamingResponseAsync(messages, options))
        {
            updates.Add(update);
        }

        return updates;
    }
}
