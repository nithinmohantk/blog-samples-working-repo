using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using Desk.Agent;

namespace Desk.Tests;

/// <summary>Writes what a test saw on the wire to DESK_OUT/wire-traces.txt, in a form short enough to read.</summary>
internal static class Trace
{
    private static readonly Lock s_gate = new();
    private static readonly JsonSerializerOptions s_indented = new() { WriteIndented = true };

    public static void Write(string scenario, IReadOnlyList<WireEntry> entries)
    {
        if (Environment.GetEnvironmentVariable("DESK_OUT") is not { Length: > 0 } folder)
        {
            return;
        }

        StringBuilder text = new($"## {scenario}\n");
        for (int i = 0; i < entries.Count; i++)
        {
            WireEntry entry = entries[i];
            JsonObject request = entry.Request.AsObject();
            text.Append($"request {i + 1}: messages={Roles(request)} state={request["state"]?.ToJsonString() ?? "none"} resume={request["resume"]?.ToJsonString() ?? "none"}\n");
            text.Append($"events {i + 1}: {Collapse(entry.Events)}{(entry.Completed ? "" : "  [stream ended early]")}\n");
            foreach (JsonNode payload in entry.Payloads)
            {
                text.Append(payload.ToJsonString(s_indented)).Append('\n');
            }
        }

        lock (s_gate)
        {
            File.AppendAllText(Path.Combine(folder, "wire-traces.txt"), text.Append('\n').ToString());
        }
    }

    private static string Roles(JsonObject request)
        => "[" + string.Join(", ", (request["messages"]?.AsArray() ?? []).Select(m => m?["role"]?.GetValue<string>())) + "]";

    /// <summary>RUN_STARTED, TEXT_MESSAGE_CONTENT x12, ... : repeats are counted, order is kept.</summary>
    private static string Collapse(IReadOnlyList<string> events)
    {
        List<string> parts = [];
        for (int i = 0; i < events.Count;)
        {
            int j = i;
            while (j < events.Count && events[j] == events[i])
            {
                j++;
            }

            parts.Add(j - i > 1 ? $"{events[i]} x{j - i}" : events[i]);
            i = j;
        }

        return string.Join(", ", parts);
    }
}
