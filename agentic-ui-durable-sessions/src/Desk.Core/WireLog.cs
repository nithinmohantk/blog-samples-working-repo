using System.Text.Json;
using System.Text.Json.Nodes;

namespace Desk.Core;

/// <summary>One request to the agent endpoint and the events sent back for it.</summary>
public sealed record WireEntry(JsonNode Request, IReadOnlyList<string> Events, IReadOnlyList<JsonNode> Payloads, bool Completed);

/// <summary>
/// Keeps what crossed the wire, for tests and for the lab. Give it a file path to also append each
/// entry as a line of JSON. This records conversation content: a test tool, not production logging.
/// </summary>
public sealed class WireLog(string? file = null)
{
    private readonly Lock _gate = new();
    private readonly List<WireEntry> _entries = [];

    public IReadOnlyList<WireEntry> Entries
    {
        get { lock (_gate) { return [.. _entries]; } }
    }

    public void Clear()
    {
        lock (_gate) { _entries.Clear(); }
    }

    public void Add(WireEntry entry)
    {
        lock (_gate)
        {
            _entries.Add(entry);
            if (file is not null)
            {
                File.AppendAllText(file, JsonSerializer.Serialize(entry) + Environment.NewLine);
            }
        }
    }
}
