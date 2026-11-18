using System.Runtime.CompilerServices;
using System.Text.Json;
using System.Text.Json.Nodes;
using AGUI.Abstractions;

namespace Desk.Agent;

/// <summary>One request to the agent endpoint and the events sent back for it.</summary>
public sealed record WireEntry(JsonNode Request, IReadOnlyList<string> Events, IReadOnlyList<JsonNode> Payloads, bool Completed);

/// <summary>
/// Keeps what crossed the wire, for tests and for the lab. Set DESK_WIRE_LOG to a file path to also
/// append each entry as a line of JSON. This records conversation content: a test tool, not production logging.
/// </summary>
public sealed class WireLog(IConfiguration configuration)
{
    private readonly Lock _gate = new();
    private readonly List<WireEntry> _entries = [];
    private readonly string? _file = configuration["DESK_WIRE_LOG"];

    public IReadOnlyList<WireEntry> Entries
    {
        get { lock (_gate) { return [.. _entries]; } }
    }

    public void Clear()
    {
        lock (_gate) { _entries.Clear(); }
    }

    public async IAsyncEnumerable<BaseEvent> RecordAsync(
        RunAgentInput input,
        IAsyncEnumerable<BaseEvent> events,
        JsonSerializerOptions json,
        [EnumeratorCancellation] CancellationToken cancellationToken)
    {
        JsonNode request = JsonSerializer.SerializeToNode(input, json.GetTypeInfo(typeof(RunAgentInput)))!;
        List<string> types = [];
        List<JsonNode> payloads = [];
        bool completed = false;
        try
        {
            await foreach (BaseEvent item in events.WithCancellation(cancellationToken))
            {
                types.Add(item.Type);
                if (item is RunFinishedEvent or StateSnapshotEvent or RunErrorEvent)
                {
                    payloads.Add(JsonSerializer.SerializeToNode(item, json.GetTypeInfo(item.GetType()))!);
                }

                yield return item;
            }

            completed = true;
        }
        finally
        {
            WireEntry entry = new(request, types, payloads, completed);
            lock (_gate)
            {
                _entries.Add(entry);
                if (_file is not null)
                {
                    File.AppendAllText(_file, JsonSerializer.Serialize(entry) + Environment.NewLine);
                }
            }
        }
    }
}
