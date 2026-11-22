using System.Text;
using System.Text.Json;
using AGUI.Abstractions;
using Microsoft.AspNetCore.Components.AI;
using Microsoft.Extensions.AI;

namespace Desk.Web.Conversations;

/// <summary>
/// The conversation as the UI agent sees it, kept in a journal. A finished turn is stored in one
/// transaction. A turn that is still arriving is stored as it arrives by <see cref="TurnRecorder"/>,
/// so a page that goes away in the middle of an answer leaves what it had.
/// A new instance for the same thread reads the journal back, and the agent can restore from it.
/// </summary>
public sealed class JournalThread : IConversationThread
{
    private static readonly JsonSerializerOptions s_json = CreateJson();

    private readonly Lock _gate = new();
    private readonly JournalStore _store;
    private readonly bool _compact;
    private readonly List<ChatResponseUpdate> _updates = [];
    private readonly List<ChatResponseUpdate> _turn = [];
    private readonly HashSet<string> _restoredApprovals = new(StringComparer.Ordinal);
    private readonly HashSet<string> _answeredApprovals = new(StringComparer.Ordinal);
    private long _nextSeq;
    private long _liveSeq;

    public JournalThread(JournalStore store, string threadId, bool compact = true, bool repairToolResults = true)
    {
        _store = store;
        _compact = compact;
        ThreadId = threadId;

        List<JournalRow> rows = store.Load(threadId);
        foreach (JournalRow row in rows.Where(row => row.Kind == JournalStore.Update))
        {
            ChatResponseUpdate update = JsonSerializer.Deserialize<ChatResponseUpdate>(row.Body!, s_json)!;
            if (repairToolResults)
            {
                RepairToolResults(update);
            }

            _updates.Add(update);
            Note(update, restored: true);
        }

        _nextSeq = rows.Count == 0 ? 0 : rows[^1].Seq + 1;
        _liveSeq = _nextSeq;
        RestoredUpdates = _updates.Count;
        EndedMidTurn = rows.Count > 0 && rows[^1].Kind != JournalStore.TurnDone;
    }

    public string ThreadId { get; }

    /// <summary>False: the agent service keeps no history, so the client sends the whole conversation every time.</summary>
    public bool IsStateful => false;

    public string? ConversationId => null;

    /// <summary>How many updates were read from storage when this instance was created.</summary>
    public int RestoredUpdates { get; }

    /// <summary>True when the journal stops before the end of a turn: the page went away while an answer was arriving.</summary>
    public bool EndedMidTurn { get; }

    /// <summary>True for an approval request that came from storage and not from this page's own run.</summary>
    public bool WasRestored(string callId) => _restoredApprovals.Contains(callId);

    /// <summary>True when the journal also holds an answer to that approval request.</summary>
    public bool WasAnswered(string callId)
    {
        lock (_gate)
        {
            return _answeredApprovals.Contains(callId);
        }
    }

    // The UI agent tells the thread about a turn only when the turn is over: the user's message, every
    // update and the end mark arrive together. These three methods collect the turn and store it in one
    // transaction, replacing whatever the recorder wrote while the answer was arriving.

    public void AppendUserMessage(ChatMessage message)
    {
        lock (_gate)
        {
            _turn.Clear();
            _turn.Add(AsUpdate(message));
        }
    }

    public void AppendUpdate(ChatResponseUpdate update)
    {
        lock (_gate)
        {
            _turn.Add(update);
        }
    }

    public void CompleteTurn()
    {
        lock (_gate)
        {
            List<ChatResponseUpdate> final = _compact ? Compact(_turn) : [.. _turn];
            List<JournalRow> rows = [.. final.Select((update, i) => new JournalRow(_nextSeq + i, JournalStore.Update, JsonSerializer.Serialize(update, s_json)))];
            rows.Add(new JournalRow(_nextSeq + final.Count, JournalStore.TurnDone, null));
            _store.Rewrite(ThreadId, _nextSeq, rows);

            foreach (ChatResponseUpdate update in final)
            {
                _updates.Add(update);
                Note(update, restored: false);
            }

            _nextSeq += rows.Count;
            _liveSeq = _nextSeq;
            _turn.Clear();
        }
    }

    public IReadOnlyList<ChatResponseUpdate> GetUpdates()
    {
        lock (_gate)
        {
            return [.. _updates];
        }
    }

    // What the recorder calls while an answer is arriving. These rows are provisional: they are what a
    // reload finds if the turn never ends, and they are replaced when it does.

    public void LiveStart(ChatMessage message)
    {
        lock (_gate)
        {
            _liveSeq = _nextSeq;
            _store.Rewrite(ThreadId, _liveSeq, [new JournalRow(_liveSeq, JournalStore.Update, JsonSerializer.Serialize(AsUpdate(message), s_json))]);
            _liveSeq++;
        }
    }

    public void Live(ChatResponseUpdate update)
    {
        lock (_gate)
        {
            _store.Append(ThreadId, new JournalRow(_liveSeq++, JournalStore.Update, JsonSerializer.Serialize(update, s_json)));
        }
    }

    private static ChatResponseUpdate AsUpdate(ChatMessage message)
        => new(message.Role, [.. message.Contents]) { MessageId = message.MessageId ?? Guid.NewGuid().ToString("N") };

    private void Note(ChatResponseUpdate update, bool restored)
    {
        foreach (AIContent content in update.Contents)
        {
            if (restored && content is ToolApprovalRequestContent { ToolCall: FunctionCallContent asked })
            {
                _restoredApprovals.Add(asked.CallId);
            }
            else if (content is ToolApprovalResponseContent { ToolCall: FunctionCallContent answered })
            {
                _answeredApprovals.Add(answered.CallId);
            }
        }
    }

    /// <summary>
    /// An answer arrives a word at a time, one update per word. Once the turn is over, the words of one
    /// message are stored as one update. What the agent restores from it is the same.
    /// </summary>
    private static List<ChatResponseUpdate> Compact(List<ChatResponseUpdate> turn)
    {
        List<ChatResponseUpdate> merged = [];
        StringBuilder? text = null;
        foreach (ChatResponseUpdate update in turn)
        {
            bool textOnly = update.Contents.Count == 1 && update.Contents[0] is TextContent && update.FinishReason is null;
            if (textOnly && text is not null && merged[^1].MessageId == update.MessageId && merged[^1].Role == update.Role)
            {
                text.Append(update.Text);
                continue;
            }

            Flush();
            merged.Add(update);
            text = textOnly ? new StringBuilder(update.Text) : null;
        }

        Flush();
        return merged;

        void Flush()
        {
            if (text is not null)
            {
                ChatResponseUpdate first = merged[^1];
                merged[^1] = new ChatResponseUpdate(first.Role, text.ToString()) { MessageId = first.MessageId, ResponseId = first.ResponseId, CreatedAt = first.CreatedAt };
                text = null;
            }
        }
    }

    /// <summary>
    /// A tool result is typed as object. Live, the AG-UI client puts a string of JSON there. Read back
    /// from storage, the same value is a JsonElement that holds a string, and a typed tool block that
    /// expects the string fails on it. This puts the string back.
    /// </summary>
    private static void RepairToolResults(ChatResponseUpdate update)
    {
        foreach (FunctionResultContent result in update.Contents.OfType<FunctionResultContent>())
        {
            if (result.Result is JsonElement { ValueKind: JsonValueKind.String } text)
            {
                result.Result = text.GetString();
            }
        }
    }

    private static JsonSerializerOptions CreateJson()
    {
        // The content types of Microsoft.Extensions.AI, plus the ones AG-UI adds for interrupts.
        JsonSerializerOptions options = new(AIJsonUtilities.DefaultOptions) { WriteIndented = false };
        AGUIJsonUtilities.RegisterInterruptContentTypes(options);
        return options;
    }
}
