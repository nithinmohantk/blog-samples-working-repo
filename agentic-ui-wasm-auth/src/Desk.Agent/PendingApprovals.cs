using System.Collections.Concurrent;
using System.Runtime.CompilerServices;
using System.Text;
using System.Text.Json;
using AGUI.Abstractions;
using Desk.Core;

namespace Desk.Agent;

/// <summary>Why an approval was not accepted, and the HTTP status that says so.</summary>
public sealed record ApprovalRefusal(int Status, string Detail);

/// <summary>
/// Remembers which tool calls this server stopped for approval, and for whom. An approval is accepted
/// only from the person it was asked of, for the call the server proposed, once, within a time limit.
/// In memory: with more than one instance this belongs in a shared store.
/// </summary>
public sealed class PendingApprovals(TimeProvider clock)
{
    private static readonly TimeSpan s_lifetime = TimeSpan.FromMinutes(10);
    private readonly ConcurrentDictionary<string, Pending> _pending = new(StringComparer.Ordinal);

    private sealed record Pending(string Owner, string Fingerprint, DateTimeOffset Expires);

    /// <summary>On the way out: note every tool call that a run ends on waiting for approval, and who was asked.</summary>
    public async IAsyncEnumerable<BaseEvent> WatchAsync(IAsyncEnumerable<BaseEvent> events, string owner, [EnumeratorCancellation] CancellationToken cancellationToken)
    {
        Dictionary<string, (string Name, StringBuilder Arguments)> calls = new(StringComparer.Ordinal);
        await foreach (BaseEvent item in events.WithCancellation(cancellationToken))
        {
            switch (item)
            {
                case ToolCallStartEvent start:
                    calls[start.ToolCallId] = (start.ToolCallName, new StringBuilder());
                    break;
                case ToolCallArgsEvent arguments when calls.TryGetValue(arguments.ToolCallId, out var call):
                    call.Arguments.Append(arguments.Delta);
                    break;
                case RunFinishedEvent { Outcome: RunFinishedInterruptOutcome { Interrupts: { } interrupts } }:
                    foreach (AGUIInterrupt interrupt in interrupts)
                    {
                        if (interrupt.ToolCallId is { } id && calls.TryGetValue(id, out var proposed))
                        {
                            using JsonDocument parsed = JsonDocument.Parse(proposed.Arguments.Length == 0 ? "{}" : proposed.Arguments.ToString());
                            _pending[interrupt.Id] = new Pending(owner, ToolCallFingerprint.Of(proposed.Name, parsed.RootElement), clock.GetUtcNow() + s_lifetime);
                        }
                    }

                    break;
            }

            yield return item;
        }
    }

    /// <summary>On the way in: every resume entry must match a pending approval asked of this person. A match is used up.</summary>
    public ApprovalRefusal? Redeem(IList<AGUIResume>? resume, string owner)
    {
        foreach (AGUIResume entry in resume ?? [])
        {
            if (!_pending.TryGetValue(entry.InterruptId, out Pending? pending))
            {
                return new(StatusCodes.Status409Conflict, "No approval is pending for this interrupt. It was never asked for, was already answered, or was asked by another server instance.");
            }

            // Checked before the entry is removed: somebody else's request must not use up the approval.
            if (!string.Equals(pending.Owner, owner, StringComparison.Ordinal))
            {
                return new(StatusCodes.Status403Forbidden, "This approval was asked of somebody else.");
            }

            _pending.TryRemove(entry.InterruptId, out _);
            if (pending.Expires < clock.GetUtcNow())
            {
                return new(StatusCodes.Status409Conflict, "The approval request has expired.");
            }

            if (entry.Payload is not { ValueKind: JsonValueKind.Object } payload
                || !payload.TryGetProperty("toolCall", out JsonElement call)
                || !call.TryGetProperty("name", out JsonElement name)
                || ToolCallFingerprint.Of(name.GetString() ?? "", call.TryGetProperty("arguments", out JsonElement arguments) ? arguments : default) != pending.Fingerprint)
            {
                return new(StatusCodes.Status409Conflict, "The tool call in the approval is not the one that was proposed.");
            }
        }

        return null;
    }
}
