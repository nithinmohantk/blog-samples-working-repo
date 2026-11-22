using System.Reflection;
using System.Text;
using System.Text.Json;
using AGUI.Abstractions;
using AGUI.Client;
using Desk.Agent;
using Desk.Core;
using Microsoft.AspNetCore.Components.AI;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.Extensions.AI;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging.Abstractions;
using Xunit;

namespace Desk.Tests;

/// <summary>Not a test of the sample: a look at what the preview's conversation thread does, written to thread-lab.txt.</summary>
public sealed class ThreadLab(WebApplicationFactory<AgentService> factory) : IClassFixture<WebApplicationFactory<AgentService>>
{
    private readonly StringBuilder _log = new();

    [Fact]
    public async Task Explore()
    {
        try
        {
            await RunAsync();
        }
        catch (Exception error)
        {
            Say("EXCEPTION " + error);
        }

        Trace.Line("thread-lab.txt", _log.ToString());
    }

    private async Task RunAsync()
    {
        WebApplicationFactory<AgentService> host = factory.WithWebHostBuilder(h => h.UseSetting("DESK_WORD_DELAY_MS", "0"));
        WireLog wire = host.Services.GetRequiredService<WireLog>();
        Ledger ledger = host.Services.GetRequiredService<Ledger>();
        IChatClient chat = new AGUIChatClient(new AGUIChatClientOptions(host.CreateClient(), "/agent"));
        JsonSerializerOptions json = new(AIJsonUtilities.DefaultOptions);
        AGUIJsonUtilities.RegisterInterruptContentTypes(json);

        Say("# types that implement IConversationThread");
        foreach (Type type in typeof(UIAgent).Assembly.GetTypes().Where(t => typeof(IConversationThread).IsAssignableFrom(t) && !t.IsInterface))
        {
            Say($"{type.FullName} public={type.IsPublic} ctors=[{string.Join("; ", type.GetConstructors(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance).Select(c => "(" + string.Join(", ", c.GetParameters().Select(p => p.ParameterType.Name + " " + p.Name)) + ")"))}]");
        }

        // ---- a first agent, with a recording thread around whatever the default is
        Recording? recording = null;
        UIAgent agent = Make(chat, "t-lab-1", inner => recording = new Recording(inner, Say));
        Say("\n# turn 1: order lookup");
        await SendAsync(agent, new ChatMessage(ChatRole.User, "Where is order O-1001?"));
        Say("\n# turn 2: refund, stops for approval");
        Task pending = SendAsync(agent, new ChatMessage(ChatRole.User, "Refund order O-1003"));
        await Task.WhenAny(pending, Task.Delay(3000));
        Say($"send completed while approval is pending: {pending.IsCompleted}");
        Say($"wire requests so far: {wire.Entries.Count}; ledger attempts: {ledger.Attempts}");

        // ---- persist what the thread holds
        IReadOnlyList<ChatResponseUpdate> updates = recording!.Inner.GetUpdates();
        Say($"\n# GetUpdates: {updates.Count} updates");
        foreach (ChatResponseUpdate update in updates)
        {
            Say($"  role={update.Role} messageId={update.MessageId} finish={update.FinishReason} raw={update.RawRepresentation?.GetType().Name ?? "null"} contents=[{string.Join(", ", update.Contents.Select(c => c.GetType().Name))}] text={Short(update.Text)}");
        }

        string stored = JsonSerializer.Serialize(updates, json);
        Say($"serialised: {stored.Length} characters");
        Say(stored.Length > 2500 ? stored[..2500] + " ..." : stored);
        List<ChatResponseUpdate> loaded = JsonSerializer.Deserialize<List<ChatResponseUpdate>>(stored, json)!;
        Say("after a round trip through JSON:");
        foreach (ChatResponseUpdate update in loaded)
        {
            Say($"  role={update.Role} messageId={update.MessageId} raw={update.RawRepresentation?.GetType().Name ?? "null"} contents=[{string.Join(", ", update.Contents.Select(c => c.GetType().Name))}]");
        }

        // ---- a second agent, as after a page reload: same thread content, new everything else
        Say("\n# restore into a new agent from the stored updates");
        Recording? second = null;
        UIAgent restored = Make(chat, "t-lab-1", inner => second = new Recording(new Stored(inner, loaded), Say));
        AgentContext context = new(restored);
        Say($"before restore: status={context.Status} turns={context.Turns.Count}");
        IReadOnlyList<ContentBlock> blocks = await restored.RestoreAsync(CancellationToken.None);
        Say($"RestoreAsync returned {blocks.Count} blocks");
        foreach (ContentBlock block in blocks)
        {
            Say("  " + Describe(block));
        }

        Say($"agent context after agent.RestoreAsync: status={context.Status} turns={context.Turns.Count}");
        AgentContext fresh = new(Make(chat, "t-lab-1", inner => new Recording(new Stored(inner, loaded), _ => { })));
        await fresh.RestoreAsync(CancellationToken.None);
        Say($"a context restored through AgentContext.RestoreAsync: status={fresh.Status} turns={fresh.Turns.Count} blocks per turn=[{string.Join(", ", fresh.Turns.Select(t => t.RequestBlocks.Count + "+" + t.ResponseBlocks.Count))}]");

        // ---- answer the restored approval
        int before = wire.Entries.Count;
        if (blocks.OfType<FunctionApprovalBlock>().LastOrDefault() is { } approval)
        {
            Say($"\n# Approve() on the restored approval block (status {approval.Status})");
            approval.Approve();
            await Task.Delay(1500);
            Say($"after Approve(): block status={approval.Status}; new wire requests={wire.Entries.Count - before}; ledger refunds={ledger.Refunds.Count}; context status={context.Status}");
            if (wire.Entries.Count == before)
            {
                Say("# nothing was sent. Send the approval response as a message instead");
                try
                {
                    await SendAsync(restored, new ChatMessage(ChatRole.User, [approval.ApprovalRequest.CreateResponse(true)]));
                }
                catch (Exception error)
                {
                    Say("send failed: " + error.GetType().Name + ": " + error.Message);
                }

                Say($"after sending the response: new wire requests={wire.Entries.Count - before}; ledger refunds={ledger.Refunds.Count}");
            }
        }
        else
        {
            Say("no FunctionApprovalBlock among the restored blocks");
        }

        foreach (WireEntry entry in wire.Entries.Skip(before))
        {
            Say($"  wire: messages={entry.Request["messages"]?.AsArray().Count} roles=[{string.Join(",", entry.Request["messages"]!.AsArray().Select(m => m!["role"]))}] resume={(entry.Request["resume"] is null ? "none" : "present")} events={entry.Events.Count} last={entry.Events.LastOrDefault()}");
        }

        // ---- and a new question on the restored conversation
        before = wire.Entries.Count;
        Say("\n# a new question after restore");
        await SendAsync(restored, new ChatMessage(ChatRole.User, "Where is order O-1002?"));
        foreach (WireEntry entry in wire.Entries.Skip(before))
        {
            Say($"  wire: threadId={entry.Request["threadId"]} messages={entry.Request["messages"]?.AsArray().Count} roles=[{string.Join(",", entry.Request["messages"]!.AsArray().Select(m => m!["role"]))}]");
        }

        Say($"\n# the first agent, still waiting: completed={pending.IsCompleted}");
    }

    private UIAgent Make(IChatClient chat, string threadId, Func<IConversationThread?, IConversationThread?> wrap)
        => new UIAgent(chat, options =>
        {
            Say($"options.Thread by default: {options.Thread?.GetType().FullName ?? "null"}" + (options.Thread is { } t ? $" threadId={t.ThreadId} stateful={t.IsStateful} conversationId={t.ConversationId ?? "null"}" : ""));
            if (wrap(options.Thread) is { } replacement)
            {
                options.Thread = replacement;
            }

            options.ChatOptions = new ChatOptions { RawRepresentationFactory = _ => new RunAgentInput { ThreadId = threadId } };
        }, NullLoggerFactory.Instance);

    private async Task SendAsync(UIAgent agent, ChatMessage message)
    {
        await foreach (ContentBlock block in agent.SendMessageAsync(message, CancellationToken.None))
        {
            Say("  block: " + Describe(block));
        }
    }

    private static string Describe(ContentBlock block) => block switch
    {
        FunctionApprovalBlock a => $"{a.GetType().Name} id={a.Id} role={a.Role} life={a.LifecycleState} tool={a.ToolName} status={a.Status} hasResult={a.HasResult}",
        FunctionInvocationContentBlock f => $"{f.GetType().Name} id={f.Id} role={f.Role} life={f.LifecycleState} tool={f.ToolName} hasResult={f.HasResult}",
        RichContentBlock r => $"{r.GetType().Name} id={r.Id} role={r.Role} life={r.LifecycleState} text={Short(r.RawText)}",
        _ => $"{block.GetType().Name} id={block.Id} role={block.Role} life={block.LifecycleState}",
    };

    private static string Short(string? text) => text is null ? "null" : "\"" + (text.Length > 50 ? text[..50] + "..." : text) + "\"";

    private void Say(string line) => _log.AppendLine(line);

    /// <summary>Passes every call to the inner thread and writes down what was asked.</summary>
    private sealed class Recording(IConversationThread? inner, Action<string> say) : IConversationThread
    {
        public IConversationThread Inner { get; } = inner ?? new Memory("t-lab-1");

        public string ThreadId => Inner.ThreadId;

        public bool IsStateful => Inner.IsStateful;

        public string? ConversationId => Inner.ConversationId;

        public void AppendUserMessage(ChatMessage message)
        {
            say($"  thread.AppendUserMessage(role={message.Role}, contents=[{string.Join(", ", message.Contents.Select(c => c.GetType().Name))}])");
            Inner.AppendUserMessage(message);
        }

        public void AppendUpdate(ChatResponseUpdate update)
        {
            say($"  thread.AppendUpdate(role={update.Role}, contents=[{string.Join(", ", update.Contents.Select(c => c.GetType().Name))}], raw={update.RawRepresentation?.GetType().Name ?? "null"})");
            Inner.AppendUpdate(update);
        }

        public void CompleteTurn()
        {
            say("  thread.CompleteTurn()");
            Inner.CompleteTurn();
        }

        public IReadOnlyList<ChatResponseUpdate> GetUpdates()
        {
            IReadOnlyList<ChatResponseUpdate> updates = Inner.GetUpdates();
            say($"  thread.GetUpdates() -> {updates.Count}");
            return updates;
        }
    }

    /// <summary>A thread that starts with updates read from storage, and otherwise behaves like the one it wraps.</summary>
    private sealed class Stored(IConversationThread? inner, List<ChatResponseUpdate> loaded) : IConversationThread
    {
        private readonly IConversationThread _inner = inner ?? new Memory("t-lab-1");

        public string ThreadId => _inner.ThreadId;

        public bool IsStateful => _inner.IsStateful;

        public string? ConversationId => _inner.ConversationId;

        public void AppendUserMessage(ChatMessage message) => _inner.AppendUserMessage(message);

        public void AppendUpdate(ChatResponseUpdate update) => _inner.AppendUpdate(update);

        public void CompleteTurn() => _inner.CompleteTurn();

        public IReadOnlyList<ChatResponseUpdate> GetUpdates() => [.. loaded, .. _inner.GetUpdates()];
    }

    /// <summary>The simplest thread that could work: every user message and every update, in order.</summary>
    private sealed class Memory(string threadId) : IConversationThread
    {
        private readonly List<ChatResponseUpdate> _updates = [];

        public string ThreadId => threadId;

        public bool IsStateful => false;

        public string? ConversationId => null;

        public void AppendUserMessage(ChatMessage message)
            => _updates.Add(new ChatResponseUpdate(message.Role, [.. message.Contents]) { MessageId = message.MessageId ?? Guid.NewGuid().ToString("N") });

        public void AppendUpdate(ChatResponseUpdate update) => _updates.Add(update);

        public void CompleteTurn()
        {
        }

        public IReadOnlyList<ChatResponseUpdate> GetUpdates() => [.. _updates];
    }
}
