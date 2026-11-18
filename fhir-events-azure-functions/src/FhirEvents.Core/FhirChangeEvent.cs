using System.Text.Json;
using System.Text.Json.Nodes;

namespace FhirEvents.Core;

public enum ChangeKind
{
    Created,
    Updated,
    Deleted,
}

/// <summary>
/// One resource change as announced by the Azure Health Data Services FHIR service. The event names the
/// resource and its version. It never carries the resource itself.
/// </summary>
public sealed record FhirChangeEvent(string EventId, ChangeKind Kind, string ResourceType, string ResourceId, long Version)
{
    private const string Prefix = "Microsoft.HealthcareApis.FhirResource";

    /// <summary>
    /// Reads a delivery in the Event Grid schema (an array, type in "eventType") or the CloudEvents schema
    /// (one object or an array, type in "type"). Entries that are not FHIR change events, or are malformed,
    /// are returned as rejects with a reason and no content.
    /// </summary>
    public static (IReadOnlyList<FhirChangeEvent> Events, IReadOnlyList<string> Rejected) ParseDelivery(string json)
    {
        JsonNode? root;
        try
        {
            root = JsonNode.Parse(json);
        }
        catch (JsonException)
        {
            return ([], ["delivery is not JSON"]);
        }

        List<FhirChangeEvent> events = [];
        List<string> rejected = [];
        foreach (JsonNode? item in root as JsonArray ?? [root])
        {
            string id = (item as JsonObject)?["id"] is JsonValue v && v.TryGetValue(out string? text) ? text : "unknown";
            if (TryParse(item, out FhirChangeEvent? change, out string reason))
            {
                events.Add(change!);
            }
            else
            {
                rejected.Add($"{id}: {reason}");
            }
        }

        return (events, rejected);
    }

    private static bool TryParse(JsonNode? item, out FhirChangeEvent? change, out string reason)
    {
        change = null;
        if (item is not JsonObject envelope || envelope["data"] is not JsonObject data)
        {
            reason = "not an event with a data object";
            return false;
        }

        string type = Text(envelope["eventType"]) ?? Text(envelope["type"]) ?? "";
        ChangeKind? kind = type.StartsWith(Prefix, StringComparison.Ordinal) && Enum.TryParse(type[Prefix.Length..], out ChangeKind parsed)
            ? parsed
            : null;
        if (kind is null)
        {
            reason = "not a FHIR resource change event";
            return false;
        }

        string? resourceType = Text(data["resourceType"]), resourceId = Text(data["resourceFhirId"]);
        // The documentation types the version as "string(number)" and its sample shows a bare number. Accept both.
        long version = data["resourceVersionId"] switch
        {
            JsonValue value when value.TryGetValue(out long number) => number,
            JsonValue value when value.TryGetValue(out string? s) && long.TryParse(s, out long number) => number,
            _ => 0,
        };
        if (string.IsNullOrEmpty(resourceType) || string.IsNullOrEmpty(resourceId) || version < 1 || Text(envelope["id"]) is not { Length: > 0 } eventId)
        {
            reason = "missing id, resource type, resource id or version";
            return false;
        }

        change = new FhirChangeEvent(eventId, kind.Value, resourceType, resourceId, version);
        reason = "";
        return true;
    }

    private static string? Text(JsonNode? node) => node is JsonValue value && value.TryGetValue(out string? text) ? text : null;
}
