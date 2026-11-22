using System.Text.Json;
using AGUI.Abstractions;
using Desk.Web.Components;
using Microsoft.AspNetCore.Components.AI;
using Microsoft.Extensions.AI;

namespace Desk.Web.Conversations;

/// <summary>Marks this assembly for tests.</summary>
public sealed class WebApp;

/// <summary>
/// One open conversation: the UI agent, the journal it writes to, and the shared state kept beside it.
/// Opening a thread that has a journal gives an agent that can restore from it.
/// </summary>
public sealed class DeskSession : IDisposable
{
    private static readonly JsonSerializerOptions s_json = new(JsonSerializerDefaults.Web);
    private readonly IDisposable _stateSubscription;

    private DeskSession(UIAgent<CaseState> agent, JournalThread thread, IDisposable stateSubscription)
    {
        Agent = agent;
        Thread = thread;
        _stateSubscription = stateSubscription;
    }

    public UIAgent<CaseState> Agent { get; }

    public JournalThread Thread { get; }

    public static DeskSession Open(IChatClient chat, JournalStore store, string threadId, ILoggerFactory loggers, bool compact = true, bool repairToolResults = true, bool recordWhileStreaming = true)
    {
        JournalThread thread = new(store, threadId, compact, repairToolResults);
        if (recordWhileStreaming)
        {
            chat = new TurnRecorder(chat, thread);
        }


        // The shared state is not part of what the agent restores, so it is stored next to the journal.
        CaseState state = store.LoadState(threadId) is { } saved ? JsonSerializer.Deserialize<CaseState>(saved, s_json)! : new CaseState();

        UIAgent<CaseState> agent = new(chat, options =>
        {
            options.AddGeneratedToolBlocks();
            options.Thread = thread;
            options.ChatOptions = new ChatOptions
            {
                RawRepresentationFactory = _ => new RunAgentInput
                {
                    ThreadId = threadId,
                    State = JsonSerializer.SerializeToElement(options.State.Value, s_json),
                },
            };
            options.StateMapper = context =>
            {
                if (context.Update.RawRepresentation is StateSnapshotEvent snapshot
                    && snapshot.Snapshot.Deserialize<CaseState>(s_json) is { } next)
                {
                    context.SetState(next);
                }
            };
        }, loggers, state);

        IDisposable subscription = agent.State.OnChanged(() => store.SaveState(threadId, JsonSerializer.Serialize(agent.State.Value, s_json)));
        return new DeskSession(agent, thread, subscription);
    }

    public void Dispose()
    {
        _stateSubscription.Dispose();
        Agent.Dispose();
    }
}
