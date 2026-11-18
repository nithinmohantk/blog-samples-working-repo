using System.Text.Json;
using System.Text.Json.Nodes;

namespace FhirMigrationValidator;

/// <summary>
/// Compares two copies of a resource and reports where they differ, as paths only.
/// Values are never written out, so the report contains no clinical content.
/// </summary>
public static class ResourceComparer
{
    /// <summary>Elements a migration is expected to change unless versions were carried across.</summary>
    public static readonly IReadOnlyList<string> ServerAssigned = ["meta.versionId", "meta.lastUpdated", "meta.source"];

    /// <param name="ignore">Dotted paths of object members to leave out of the comparison on both sides.</param>
    public static IReadOnlyList<string> Differences(JsonObject source, JsonObject target, IEnumerable<string> ignore, int limit = 10)
    {
        JsonObject left = Without(source, ignore), right = Without(target, ignore);
        List<string> found = [];
        Walk(left, right, "", found, limit);
        return found;
    }

    private static JsonObject Without(JsonObject resource, IEnumerable<string> ignore)
    {
        JsonObject copy = resource.DeepClone().AsObject();
        foreach (string path in ignore)
        {
            string[] parts = path.Split('.');
            JsonObject? parent = copy;
            foreach (string part in parts[..^1])
            {
                parent = parent?[part] as JsonObject;
            }

            parent?.Remove(parts[^1]);
        }

        // A meta element left with nothing in it is the same as no meta element.
        if (copy["meta"] is JsonObject { Count: 0 })
        {
            copy.Remove("meta");
        }

        return copy;
    }

    private static void Walk(JsonNode? a, JsonNode? b, string path, List<string> found, int limit)
    {
        if (found.Count >= limit)
        {
            return;
        }

        switch (a, b)
        {
            case (JsonObject left, JsonObject right):
                foreach (string key in left.Select(p => p.Key).Union(right.Select(p => p.Key)).Order(StringComparer.Ordinal))
                {
                    Walk(left[key], right[key], path.Length == 0 ? key : $"{path}.{key}", found, limit);
                }

                break;

            case (JsonArray left, JsonArray right) when left.Count == right.Count:
                for (int i = 0; i < left.Count; i++)
                {
                    Walk(left[i], right[i], $"{path}[{i}]", found, limit);
                }

                break;

            case (JsonArray left, JsonArray right):
                found.Add($"{path} (array length {left.Count} on source, {right.Count} on target)");
                break;

            case (null, null):
                break;

            case (JsonValue left, JsonValue right) when SameValue(left, right):
                break;

            default:
                found.Add(a is null ? $"{path} (only on target)" : b is null ? $"{path} (only on source)" : path);
                break;
        }
    }

    // 120 and 120.0 are the same number in JSON. "120" and 120 are not the same value.
    private static bool SameValue(JsonValue a, JsonValue b) =>
        a.GetValueKind() == b.GetValueKind()
        && (a.GetValueKind() == JsonValueKind.Number
            ? a.GetValue<decimal>() == b.GetValue<decimal>()
            : a.ToJsonString() == b.ToJsonString());
}
