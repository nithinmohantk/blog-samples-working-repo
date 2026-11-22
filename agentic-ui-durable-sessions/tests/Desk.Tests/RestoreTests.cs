using System.Diagnostics;
using System.Net;
using AGUI.Client;
using Desk.Agent;
using Desk.Core;
using Desk.Web.Components;
using Desk.Web.Conversations;
using Microsoft.AspNetCore.Components.AI;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.Extensions.AI;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging.Abstractions;
using Xunit;
using CaseState = Desk.Web.Components.CaseState;

namespace Desk.Tests;

/// <summary>
/// The UI agent with a journal behind it, talking to the agent service on an in-memory server.
/// "A reload" here is what a reload is to the server: the old objects are dropped and new ones
/// are made for the same thread id.
/// </summary>
public sealed class RestoreTests : IDisposable
{
    private readonly string _folder = Path.Combine(Path.GetTempPath(), "desk-" + Guid.NewGuid().ToString("N"));
    private readonly JournalStore _store;
    private WebApplicationFactory<AgentService> _agent;
    private IChatClient _chat;

    public RestoreTests()
    {
        Directory.CreateDirectory(_folder);
        _store = new JournalStore(Path.Combine(_folder, "conversations.db"));
        (_agent, _chat) = StartAgent(durableApprovals: true);
    }

    private Ledger Ledger => _agent.Services.GetRequiredService<Ledger>();

    private WireLog Wire => _agent.Services.GetRequiredService<WireLog>();

    public void Dispose()
    {
        _agent.Dispose();
        Microsoft.Data.Sqlite.SqliteConnection.ClearAllPools();
        try
        {
            Directory.Delete(_folder, recursive: true);
        }
        catch (IOException)
        {
        }
    }

    [Fact]
    public async Task What_comes_back_after_a_reload_is_what_was_on_the_page()
    {
        string thread = NewThread();
        (DeskSession session, AgentContext live) = Open(thread);
        await live.SendMessageAsync("Where is order O-1001?", default);
        await live.SendMessageAsync("Draft a reply for order O-1001", default);
        await AskUntilWaitingAsync(live, "Refund order O-1003");
        List<string> before = Blocks(live);

        (DeskSession reloaded, AgentContext restored) = Open(thread);
        await restored.RestoreAsync(default);
        List<string> after = Blocks(restored);

        Trace.Line("restore-results.txt", $"1 reload | live: {live.Turns.Count} turns, {before.Count} blocks, status {live.Status} | restored: {restored.Turns.Count} turns, {after.Count} blocks, status {restored.Status}");
        foreach (string line in after)
        {
            Trace.Line("restore-results.txt", "1   restored block: " + line);
        }

        Assert.Equal(before, after);
        Assert.Equal(ConversationStatus.AwaitingInput, live.Status);
        Assert.Equal(ConversationStatus.Idle, restored.Status); // the agent does not come back waiting
        Assert.True(reloaded.Thread.WasRestored(Approval(restored).Id));
        session.Dispose();
        reloaded.Dispose();
    }

    [Fact]
    public async Task A_tool_result_read_back_from_storage_breaks_the_typed_tool_card_until_it_is_repaired()
    {
        string thread = NewThread();
        (DeskSession session, AgentContext live) = Open(thread);
        await live.SendMessageAsync("Where is order O-1001?", default);
        object? liveResult = session.Thread.GetUpdates().SelectMany(u => u.Contents).OfType<FunctionResultContent>().Single().Result;

        DeskSession raw = DeskSession.Open(_chat, _store, thread, NullLoggerFactory.Instance, repairToolResults: false);
        object? storedResult = raw.Thread.GetUpdates().SelectMany(u => u.Contents).OfType<FunctionResultContent>().Single().Result;
        Exception? failure = await Record.ExceptionAsync(() => new AgentContext(raw.Agent).RestoreAsync(default));

        (DeskSession repaired, AgentContext restored) = Open(thread);
        await restored.RestoreAsync(default);

        Trace.Line("restore-results.txt", $"0 tool result | live: {liveResult?.GetType().Name} | read back from JSON: {storedResult?.GetType().Name}{(storedResult is System.Text.Json.JsonElement e ? " of kind " + e.ValueKind : "")} | restore as stored: {failure?.GetType().Name ?? "no error"} | restore after repair: {Blocks(restored).Count} blocks");
        Assert.IsType<string>(liveResult);
        Assert.IsType<System.Text.Json.JsonException>(failure);
        Assert.Equal(Blocks(live), Blocks(restored));
        session.Dispose();
        raw.Dispose();
        repaired.Dispose();
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task The_journal_with_and_without_compaction_restores_the_same_blocks(bool compact)
    {
        string thread = NewThread();
        (DeskSession session, AgentContext live) = Open(thread, compact);
        await live.SendMessageAsync("Where is order O-1001?", default);
        await live.SendMessageAsync("Draft a reply for order O-1001", default);
        await live.SendMessageAsync("hello", default);
        List<string> before = Blocks(live);
        (long rows, long characters) = _store.Size(thread);

        (DeskSession reloaded, AgentContext restored) = Open(thread, compact);
        await restored.RestoreAsync(default);

        Trace.Line("restore-results.txt", $"2 journal for three turns, compaction {(compact ? "on" : "off")} | {rows} rows, {characters} characters | restored blocks equal: {before.SequenceEqual(Blocks(restored))}");
        Assert.Equal(before, Blocks(restored));
        session.Dispose();
        reloaded.Dispose();
    }

    [Fact]
    public async Task The_shared_state_comes_back_from_its_own_row_and_not_from_the_agent()
    {
        string thread = NewThread();
        (DeskSession session, AgentContext live) = Open(thread);
        await live.SendMessageAsync("Draft a reply for order O-1001", default);
        string drafted = session.Agent.State.Value.Reply;

        // The agent alone, given the same journal and no stored state.
        UIAgent<CaseState> bare = new(_chat, options => options.Thread = new JournalThread(_store, thread), NullLoggerFactory.Instance, new CaseState());
        await new AgentContext(bare).RestoreAsync(default);

        (DeskSession reloaded, AgentContext restored) = Open(thread);
        await restored.RestoreAsync(default);

        Trace.Line("restore-results.txt", $"3 shared state | live reply: {drafted.Length} characters | agent restore alone: {bare.State.Value.Reply.Length} characters | with the stored state row: {reloaded.Agent.State.Value.Reply.Length} characters");
        Assert.NotEmpty(drafted);
        Assert.Empty(bare.State.Value.Reply);
        Assert.Equal(drafted, reloaded.Agent.State.Value.Reply);
        session.Dispose();
        reloaded.Dispose();
    }

    [Fact]
    public async Task Approve_on_a_restored_block_changes_the_label_and_sends_nothing()
    {
        string thread = NewThread();
        (DeskSession session, AgentContext live) = Open(thread);
        await AskUntilWaitingAsync(live, "Refund order O-1003");
        (DeskSession reloaded, AgentContext restored) = Open(thread);
        await restored.RestoreAsync(default);
        int requests = Wire.Entries.Count;

        FunctionApprovalBlock block = Approval(restored);
        ApprovalStatus was = block.Status;
        block.Approve();
        await Task.Delay(1500);

        Trace.Line("restore-results.txt", $"4 default Approve() on a restored approval | block status {was} -> {block.Status} | requests sent: {Wire.Entries.Count - requests} | refunds: {Ledger.Refunds.Count} | conversation status: {restored.Status}");
        Assert.Equal(ApprovalStatus.Approved, block.Status);
        Assert.Equal(requests, Wire.Entries.Count);
        Assert.Empty(Ledger.Refunds);
        session.Dispose();
        reloaded.Dispose();
    }

    [Fact]
    public async Task A_restored_approval_answered_as_a_message_pays_once_and_a_second_copy_is_refused()
    {
        string thread = NewThread();
        (DeskSession session, AgentContext live) = Open(thread);
        await AskUntilWaitingAsync(live, "Refund order O-1003");

        // Two reloads of the same conversation: two tabs.
        (DeskSession tabA, AgentContext a) = Open(thread);
        await a.RestoreAsync(default);
        (DeskSession tabB, AgentContext b) = Open(thread);
        await b.RestoreAsync(default);

        await a.SendMessageAsync(new ChatMessage(ChatRole.User, [Approval(a).ApprovalRequest.CreateResponse(true)]), default);
        int refundsAfterA = Ledger.Refunds.Count;
        ConversationStatus statusA = a.Status;

        await Quietly(b.SendMessageAsync(new ChatMessage(ChatRole.User, [Approval(b).ApprovalRequest.CreateResponse(true)]), default));

        // And a third reload, after the answer.
        (DeskSession later, AgentContext third) = Open(thread);
        await third.RestoreAsync(default);
        FunctionApprovalBlock? old = third.Turns.SelectMany(t => t.ResponseBlocks).OfType<FunctionApprovalBlock>().FirstOrDefault();

        Trace.Line("restore-results.txt", $"5 tab A answers | refunds {refundsAfterA}, status {statusA}");
        Trace.Line("restore-results.txt", $"5 tab B answers the same approval | status {b.Status}, error {(b.Error as HttpRequestException)?.StatusCode} | refunds {Ledger.Refunds.Count}, attempts {Ledger.Attempts}");
        Trace.Line("restore-results.txt", $"5 a reload after the answer | approval block: {(old is null ? "none" : old.Status.ToString())}, journal says answered: {(old is null ? "n/a" : later.Thread.WasAnswered(old.Id).ToString())} | blocks: {string.Join(" / ", Blocks(third))}");
        Assert.Equal(1, refundsAfterA);
        Assert.Equal(ConversationStatus.Error, b.Status);
        Assert.Equal(HttpStatusCode.Conflict, Assert.IsType<HttpRequestException>(b.Error).StatusCode);
        Assert.Single(Ledger.Refunds);
        Assert.Equal(1, Ledger.Attempts);
        foreach (DeskSession s in new[] { session, tabA, tabB, later })
        {
            s.Dispose();
        }
    }

    [Theory]
    [InlineData(true, 1)]
    [InlineData(false, 0)]
    public async Task An_approval_that_was_waiting_when_the_agent_service_restarted(bool durableApprovals, int refunds)
    {
        _agent.Dispose();
        (_agent, _chat) = StartAgent(durableApprovals);
        Ledger.Clear();
        string thread = NewThread();
        (DeskSession session, AgentContext live) = Open(thread);
        await AskUntilWaitingAsync(live, "Refund order O-1003");

        // The agent service stops and starts again. Whatever it kept in memory is gone.
        _agent.Dispose();
        (_agent, _chat) = StartAgent(durableApprovals);

        (DeskSession reloaded, AgentContext restored) = Open(thread);
        await restored.RestoreAsync(default);
        await Quietly(restored.SendMessageAsync(new ChatMessage(ChatRole.User, [Approval(restored).ApprovalRequest.CreateResponse(true)]), default));

        Trace.Line("restore-results.txt", $"6 agent service restarted while an approval waited, approvals {(durableApprovals ? "in SQLite" : "in memory")} | status {restored.Status}{(restored.Error is HttpRequestException error ? ", HTTP " + (int?)error.StatusCode : "")} | refunds {Ledger.Refunds.Count}");
        Assert.Equal(refunds, Ledger.Refunds.Count);
        Assert.Equal(durableApprovals ? ConversationStatus.Idle : ConversationStatus.Error, restored.Status);
        session.Dispose();
        reloaded.Dispose();
    }

    [Fact]
    public async Task A_journal_that_stops_in_the_middle_of_an_answer()
    {
        string thread = NewThread();
        (DeskSession session, AgentContext live) = Open(thread, compact: false);
        await live.SendMessageAsync("hello", default);
        string whole = Blocks(live)[^1];

        // Drop everything after the first three words of the answer, and the end-of-turn mark with it:
        // what the journal holds when the page goes away while the answer is arriving.
        List<JournalRow> rows = _store.Load(thread);
        long cut = rows.Where(row => row.Body?.Contains("\"text\"") == true && row.Body.Contains("assistant")).Skip(3).First().Seq;
        _store.Rewrite(thread, cut, []);

        (DeskSession reloaded, AgentContext restored) = Open(thread);
        await restored.RestoreAsync(default);
        string partial = Blocks(restored)[^1];
        await restored.SendMessageAsync("Where is order O-1002?", default);

        Trace.Line("restore-results.txt", $"7 journal cut mid-answer | thread says ended mid-turn: {reloaded.Thread.EndedMidTurn} | restored status {restored.Status} | whole answer: {whole} | restored: {partial} | next question: status {restored.Status}, {restored.Turns.Count} turns");
        Assert.True(reloaded.Thread.EndedMidTurn);
        Assert.NotEqual(whole, partial);
        Assert.Equal(ConversationStatus.Idle, restored.Status);
        Assert.Equal(2, restored.Turns.Count);
        session.Dispose();
        reloaded.Dispose();
    }

    [Theory]
    [InlineData(false, "the page goes away")]
    [InlineData(true, "the page goes away")]
    [InlineData(false, "the user presses Stop")]
    [InlineData(true, "the user presses Stop")]
    public async Task What_is_on_disk_when_an_answer_does_not_finish(bool recordWhileStreaming, string ending)
    {
        _agent.Dispose();
        (_agent, _chat) = StartAgent(durableApprovals: true);
        string thread = NewThread();
        DeskSession session = DeskSession.Open(_chat, _store, thread, NullLoggerFactory.Instance, recordWhileStreaming: recordWhileStreaming);
        AgentContext live = new(session.Agent);

        // "policy" makes the scripted model answer slowly: 156 words, one every 150 ms.
        Task send = live.SendMessageAsync("Explain the refund policy", default);
        await Task.Delay(1500);
        long during = _store.Size(thread).Rows;

        if (ending == "the user presses Stop")
        {
            await live.CancelAsync();
        }
        else
        {
            session.Dispose();
        }

        await Quietly(send);
        await Task.Delay(300);
        long afterwards = _store.Size(thread).Rows;
        bool endMark = _store.Load(thread).Any(row => row.Kind == JournalStore.TurnDone);

        (DeskSession reloaded, AgentContext restored) = Open(thread);
        await restored.RestoreAsync(default);
        string last = Blocks(restored).LastOrDefault() ?? "nothing";

        Trace.Line("restore-results.txt", $"7b {ending} 1.5 s into an answer, recorder {(recordWhileStreaming ? "on " : "off")} | journal rows while streaming: {during} | afterwards: {afterwards}, end mark: {endMark} | a reload shows {restored.Turns.Count} turns, ended mid-turn: {reloaded.Thread.EndedMidTurn}, last block: {(last.Length > 60 ? last[..60] + "..." : last)}");
        Assert.Equal(recordWhileStreaming, during > 0);
        reloaded.Dispose();
    }

    [Fact]
    public async Task What_a_long_conversation_costs()
    {
        string thread = NewThread();
        (DeskSession session, AgentContext live) = Open(thread);
        foreach (int turns in new[] { 10, 50, 100 })
        {
            while (live.Turns.Count < turns)
            {
                await live.SendMessageAsync($"Where is order O-100{(live.Turns.Count % 3) + 1}?", default);
            }

            (long rows, long characters) = _store.Size(thread);
            Stopwatch watch = Stopwatch.StartNew();
            (DeskSession reloaded, AgentContext restored) = Open(thread);
            await restored.RestoreAsync(default);
            double milliseconds = watch.Elapsed.TotalMilliseconds;
            int request = Wire.Entries[^1].Request.ToJsonString().Length;

            Trace.Line("restore-results.txt", $"8 after {turns,3} turns | journal {rows} rows, {characters / 1024.0:0.0} KiB | open and restore {milliseconds:0} ms, {restored.Turns.Count} turns | last request to the agent service: {Wire.Entries[^1].Request["messages"]!.AsArray().Count} messages, {request / 1024.0:0.0} KiB");
            Assert.Equal(turns, restored.Turns.Count);
            reloaded.Dispose();
        }

        session.Dispose();
    }

    [Fact]
    public async Task Twenty_requests_take_one_pending_approval_and_one_gets_it()
    {
        SqliteApprovalStore store = new(Path.Combine(_folder, "race.db"));
        store.Put("i-1", new PendingApproval("f", DateTimeOffset.UtcNow.AddMinutes(10)));

        bool[] taken = await Task.WhenAll(Enumerable.Range(0, 20).Select(_ => Task.Run(() => store.TryTake("i-1", out PendingApproval _))));

        Trace.Line("restore-results.txt", $"9 twenty concurrent answers to one pending approval in SQLite | accepted: {taken.Count(t => t)}");
        Assert.Equal(1, taken.Count(t => t));
    }

    private (WebApplicationFactory<AgentService>, IChatClient) StartAgent(bool durableApprovals)
    {
        WebApplicationFactory<AgentService> factory = new WebApplicationFactory<AgentService>().WithWebHostBuilder(host => host
            .UseSetting("DESK_WORD_DELAY_MS", "0")
            .UseSetting("DESK_DATA", _folder)
            .UseSetting("DESK_DURABLE_APPROVALS", durableApprovals.ToString()));
        return (factory, new AGUIChatClient(new AGUIChatClientOptions(factory.CreateClient(), "/agent")));
    }

    private (DeskSession, AgentContext) Open(string thread, bool compact = true)
    {
        DeskSession session = DeskSession.Open(_chat, _store, thread, NullLoggerFactory.Instance, compact);
        return (session, new AgentContext(session.Agent));
    }

    private static string NewThread() => Guid.NewGuid().ToString("N");

    /// <summary>A question that ends on an approval request does not return until the approval is answered.</summary>
    private static async Task AskUntilWaitingAsync(AgentContext context, string question)
    {
        Task send = context.SendMessageAsync(question, default);
        for (int i = 0; i < 100 && context.Status != ConversationStatus.AwaitingInput && !send.IsCompleted; i++)
        {
            await Task.Delay(50);
        }

        await Task.Delay(100);
        Assert.Equal(ConversationStatus.AwaitingInput, context.Status);
    }

    private static async Task Quietly(Task task)
    {
        try
        {
            await task.WaitAsync(TimeSpan.FromSeconds(10));
        }
        catch (Exception)
        {
            // The context records the failure; the test reads it from there.
        }
    }

    private static FunctionApprovalBlock Approval(AgentContext context)
        => context.Turns.SelectMany(turn => turn.ResponseBlocks).OfType<FunctionApprovalBlock>().Last();

    private static List<string> Blocks(AgentContext context)
        => [.. context.Turns.SelectMany(turn => turn.RequestBlocks.Concat(turn.ResponseBlocks)).Select(Describe)];

    private static string Describe(ContentBlock block) => block switch
    {
        FunctionApprovalBlock approval => $"approval {approval.ToolName} {approval.Status}",
        FunctionInvocationContentBlock call => $"{call.GetType().Name} {call.ToolName} result={call.HasResult}",
        RichContentBlock text => $"{text.Role}: \"{text.RawText}\"",
        _ => block.GetType().Name,
    };
}
