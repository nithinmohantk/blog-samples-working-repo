using System.Text;
using System.Text.Json;
using AGUI.Abstractions;
using Microsoft.AspNetCore.Components.AI;
using Microsoft.Extensions.AI;

namespace Desk.Web.Conversations;

/// <summary>
/// The conversation as the UI agent sees it, kept in a journal. The agent calls this as things
/// happen: the user's message, every update of the answer, the end of the turn. Each call is
/// written at once, so a page that goes away in the middle of an answer leaves what it had.
/// A new instance for the same thread reads the journal back, and the agent can restore from it.
/// </summary>
public sealed class JournalThread : IConversationThread
{
    private static readonly JsonSerializerOptions s_json = CreateJson();

    private readonly Lock _gate = new();
    private readonly JournalStore _store;
    private readonly bool _compact;
    private readonly List<ChatResponseUpdate> _updates = [];
    private readonly HashSet<string> _restoredApprovals = new(StringComparer.Ordinal);
    private readonly HashSet<string> _answeredApprovals = new(StringComparer.Ordinal);
    private long _nextSeq;
    private long _turnStartSeq;
    private int _turnStartIndex;

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

    public void AppendUserMessage(ChatMessage message)
    {
        lock (_gate)
        {
            _turnStartSeq = _nextSeq;
            _turnStartIndex = _updates.Count;
            Write(new ChatResponseUpdate(message.Role, [.. message.Contents]) { MessageId = message.MessageId ?? Guid.NewGuid().ToString("N") });
        }
    }

    public void AppendUpdate(ChatResponseUpdate update)
    {
        lock (_gate)
        {
            Write(update);
        }
    }

    public void CompleteTurn()
    {
        lock (_gate)
        {
            if (_compact)
            {
                Compact();
            }

            _store.Append(ThreadId, new JournalRow(_nextSeq++, JournalStore.TurnDone, null));
        }
    }

    public IReadOnlyList<ChatResponseUpdate> GetUpdates()
    {
        lock (_gate)
        {
            return [.. _updates];
        }
    }

    private void Write(ChatResponseUpdate update)
    {
        _updates.Add(update);
        Note(update, restored: false);
        _store.Append(ThreadId, new JournalRow(_nextSeq++, JournalStore.Update, JsonSerializer.Serialize(update, s_json)));
    }

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
    private void Compact()
    {
        List<ChatResponseUpdate> turn = _updates[_turnStartIndex..];
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
        if (merged.Count == turn.Count)
        {
            return;
        }

        _updates.RemoveRange(_turnStartIndex, turn.Count);
        _updates.AddRange(merged);
        _nextSeq = _turnStartSeq + merged.Count;
        _store.Rewrite(ThreadId, _turnStartSeq, [.. merged.Select((update, i) => new JournalRow(_turnStartSeq + i, JournalStore.Update, JsonSerializer.Serialize(update, s_json)))]);

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
