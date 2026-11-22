using System.Runtime.CompilerServices;
using System.Text.Json;
using System.Text.Json.Nodes;
using AGUI.Abstractions;
using Desk.Core;

namespace Desk.Agent;

/// <summary>Marks this assembly for the tests that start the service in memory.</summary>
public sealed class AgentService;

/// <summary>Records each request and the events sent back for it, as the events pass through.</summary>
public static class WireRecorder
{
    public static async IAsyncEnumerable<BaseEvent> RecordAsync(
        this WireLog log,
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
            log.Add(new WireEntry(request, types, payloads, completed));
        }
    }
}
