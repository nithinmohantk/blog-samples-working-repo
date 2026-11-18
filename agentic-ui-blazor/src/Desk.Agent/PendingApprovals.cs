using System.Collections.Concurrent;
using System.Runtime.CompilerServices;
using System.Text;
using System.Text.Json;
using AGUI.Abstractions;

namespace Desk.Agent;

/// <summary>
/// Remembers which tool calls this server stopped for approval, so that an approval is only accepted
/// for a call the server itself proposed, with the arguments it proposed, once, within a time limit.
/// Without it the endpoint runs whatever tool call an approval names, because the call travels in the
/// client's resume payload. In memory: with more than one instance this belongs in a shared store.
/// </summary>
public sealed class PendingApprovals(TimeProvider clock)
{
    private static readonly TimeSpan s_lifetime = TimeSpan.FromMinutes(10);
    private readonly ConcurrentDictionary<string, (string Fingerprint, DateTimeOffset Expires)> _pending = new(StringComparer.Ordinal);

    /// <summary>On the way out: note every tool call that a run ends on waiting for approval.</summary>
    public async IAsyncEnumerable<BaseEvent> WatchAsync(IAsyncEnumerable<BaseEvent> events, [EnumeratorCancellation] CancellationToken cancellationToken)
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
                            _pending[interrupt.Id] = (Fingerprint(proposed.Name, parsed.RootElement), clock.GetUtcNow() + s_lifetime);
                        }
                    }

                    break;
            }

            yield return item;
        }
    }

    /// <summary>On the way in: every resume entry must match a pending approval. A match is used up.</summary>
    public bool TryRedeem(IList<AGUIResume>? resume, out string problem)
    {
        problem = "";
        foreach (AGUIResume entry in resume ?? [])
        {
            if (!_pending.TryRemove(entry.InterruptId, out var pending))
            {
                problem = "No approval is pending for this interrupt. It was never asked for, was already answered, or was asked by another server instance.";
                return false;
            }

            if (pending.Expires < clock.GetUtcNow())
            {
                problem = "The approval request has expired.";
                return false;
            }

            if (entry.Payload is not { ValueKind: JsonValueKind.Object } payload
                || !payload.TryGetProperty("toolCall", out JsonElement call)
                || !call.TryGetProperty("name", out JsonElement name)
                || Fingerprint(name.GetString() ?? "", call.TryGetProperty("arguments", out JsonElement arguments) ? arguments : default) != pending.Fingerprint)
            {
                problem = "The tool call in the approval is not the one that was proposed.";
                return false;
            }
        }

        return true;
    }

    /// <summary>Tool name plus arguments in one canonical form: keys sorted, numbers by value.</summary>
    private static string Fingerprint(string name, JsonElement arguments)
    {
        StringBuilder text = new(name);
        text.Append('|');
        Canonical(arguments, text);
        return text.ToString();
    }

    private static void Canonical(JsonElement element, StringBuilder text)
    {
        switch (element.ValueKind)
        {
            case JsonValueKind.Object:
                text.Append('{');
                foreach (JsonProperty property in element.EnumerateObject().OrderBy(p => p.Name, StringComparer.Ordinal))
                {
                    text.Append(JsonEncodedText.Encode(property.Name)).Append(':');
                    Canonical(property.Value, text);
                    text.Append(',');
                }

                text.Append('}');
                break;
            case JsonValueKind.Array:
                text.Append('[');
                foreach (JsonElement item in element.EnumerateArray())
                {
                    Canonical(item, text);
                    text.Append(',');
                }

                text.Append(']');
                break;
            case JsonValueKind.Number when element.TryGetDecimal(out decimal number):
                text.Append(number.ToString("G29", System.Globalization.CultureInfo.InvariantCulture));
                break;
            case JsonValueKind.Undefined:
                text.Append("{}");
                break;
            default:
                text.Append(element.GetRawText());
                break;
        }
    }
}
