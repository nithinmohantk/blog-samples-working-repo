using System.Text.Json.Nodes;

namespace Interop;

/// <summary>What happened to every row: mapped, rejected with a reason, or mapped with something degraded.</summary>
public sealed class MappingReport
{
    public int MappedRows { get; set; }
    public List<string> Rejected { get; } = [];
    public List<string> Notes { get; } = [];
    public List<string> UnmappedColumns { get; } = [];
}

public delegate JsonNode? Transform(JsonNode? value, string order, MappingReport report);

/// <summary>One line of the mapping table: an AQL column, the FHIR element it fills, and how.</summary>
public sealed record Rule(string Column, string FhirPath, Transform Apply, bool Required = false);

/// <summary>
/// Maps an openEHR AQL result set of medication orders to a FHIR R4 transaction Bundle of
/// MedicationRequest resources. Uses only System.Text.Json.
/// </summary>
public static class MedicationOrderMapper
{
    public const string IdentifierSystem = "urn:openehr:medication-order";

    private static readonly Dictionary<string, string> Terminologies = new()
    {
        ["SNOMED-CT"] = "http://snomed.info/sct",
        ["LOINC"] = "http://loinc.org",
    };

    // openEHR instruction state (ISM) -> MedicationRequest.status. A clinical decision: review before use.
    private static readonly Dictionary<string, string> IsmToStatus = new()
    {
        ["524"] = "draft", ["526"] = "active", ["529"] = "active", ["245"] = "active",
        ["527"] = "on-hold", ["530"] = "on-hold", ["528"] = "cancelled", ["531"] = "stopped",
        ["532"] = "completed", ["533"] = "stopped",
    };

    private static readonly Rule[] Rules =
    [
        new("medication", "medicationCodeableConcept", Codeable, Required: true),
        new("authored", "authoredOn", Text),
        new("directions", "dosageInstruction[0].text", Text),
        new("route", "dosageInstruction[0].route", Codeable),
        new("start", "dosageInstruction[0].timing.repeat.boundsPeriod.start", Text),
        new("stop", "dosageInstruction[0].timing.repeat.boundsPeriod.end", Text),
        new("indication", "reasonCode[0].text", Text),
    ];

    private static readonly HashSet<string> StructuralColumns = ["ehr_id", "composition_uid", "order_id"];

    public static (JsonObject Bundle, MappingReport Report) ToBundle(
        JsonNode orders, JsonNode actions, IReadOnlyDictionary<string, string> patientIndex)
    {
        MappingReport report = new();
        JsonArray entries = [];
        string[] names = ColumnNames(orders);
        report.UnmappedColumns.AddRange(
            names.Where(n => !StructuralColumns.Contains(n) && Rules.All(r => r.Column != n)));
        Dictionary<string, string> states = LatestStates(actions);

        foreach (JsonNode? row in orders["rows"]!.AsArray())
        {
            Dictionary<string, JsonNode?> record = names.Zip(row!.AsArray()).ToDictionary(p => p.First, p => p.Second);
            string? orderId = (string?)record["order_id"];
            string order = orderId ?? "(no order id)";
            string ehrId = (string)record["ehr_id"]!;

            if (!patientIndex.TryGetValue(ehrId, out string? patientId))
            {
                report.Rejected.Add($"{order}: no FHIR Patient for EHR {ehrId}");
                continue;
            }

            string[] missing = [.. Rules.Where(r => r.Required && record[r.Column] is null).Select(r => r.Column)];
            if (missing.Length > 0 || orderId is null)
            {
                report.Rejected.Add($"{order}: missing required {(missing.Length > 0 ? string.Join(", ", missing) : "order_id")}");
                continue;
            }

            string status = states.TryGetValue(order, out string? state) && IsmToStatus.TryGetValue(state, out string? mapped)
                ? mapped
                : "unknown";
            if (status == "unknown")
            {
                report.Notes.Add($"{order}: no usable state from ACTION entries; status set to unknown");
            }

            // The identifier is stable across composition versions, so a new version replaces the resource.
            string compositionUid = (string)record["composition_uid"]!;
            string versionedObject = compositionUid[..compositionUid.LastIndexOf("::", StringComparison.Ordinal)];
            string identifier = $"{versionedObject}:{order}";

            JsonObject resource = new()
            {
                ["resourceType"] = "MedicationRequest",
                ["meta"] = new JsonObject { ["source"] = $"urn:openehr:composition:{compositionUid}" },
                ["identifier"] = new JsonArray(new JsonObject { ["system"] = IdentifierSystem, ["value"] = identifier }),
                ["status"] = status,
                ["intent"] = "order",
                ["subject"] = new JsonObject { ["reference"] = $"Patient/{patientId}" },
            };

            foreach (Rule rule in Rules)
            {
                JsonNode? value = rule.Apply(record[rule.Column], order, report);
                if (value is not null)
                {
                    SetPath(resource, rule.FhirPath, value);
                }
            }

            foreach (string column in report.UnmappedColumns.Where(c => record[c] is not null))
            {
                report.Notes.Add($"{order}: column '{column}' has a value and no mapping rule");
            }

            entries.Add(new JsonObject
            {
                ["resource"] = resource,
                // Conditional update: running the same batch twice creates nothing new.
                ["request"] = new JsonObject
                {
                    ["method"] = "PUT",
                    ["url"] = $"MedicationRequest?identifier={Uri.EscapeDataString(IdentifierSystem)}%7C{Uri.EscapeDataString(identifier)}",
                },
            });
            report.MappedRows++;
        }

        return (new JsonObject { ["resourceType"] = "Bundle", ["type"] = "transaction", ["entry"] = entries }, report);
    }

    /// <summary>The current state of an order is the state of its most recent ACTION, not a field on the order.</summary>
    public static Dictionary<string, string> LatestStates(JsonNode actions)
    {
        string[] names = ColumnNames(actions);
        int order = Array.IndexOf(names, "order_id"), time = Array.IndexOf(names, "time"), state = Array.IndexOf(names, "state");
        return actions["rows"]!.AsArray()
            .Select(r => r!.AsArray())
            .GroupBy(r => (string)r[order]!)
            .ToDictionary(
                g => g.Key,
                g => (string)g.OrderBy(r => (string)r[time]!, StringComparer.Ordinal).Last()[state]!);
    }

    /// <summary>Sets "a.b[0].c" on a nested object, creating objects and array slots as needed.</summary>
    public static void SetPath(JsonObject resource, string path, JsonNode value)
    {
        JsonObject node = resource;
        string[] parts = path.Split('.');
        for (int i = 0; i < parts.Length; i++)
        {
            bool last = i == parts.Length - 1;
            int bracket = parts[i].IndexOf('[');
            if (bracket < 0)
            {
                if (last)
                {
                    node[parts[i]] = value;
                }
                else
                {
                    node = (JsonObject)(node[parts[i]] ??= new JsonObject());
                }

                continue;
            }

            string name = parts[i][..bracket];
            int slot = int.Parse(parts[i][(bracket + 1)..^1]);
            JsonArray items = (JsonArray)(node[name] ??= new JsonArray());
            while (items.Count <= slot)
            {
                items.Add(new JsonObject());
            }

            if (last)
            {
                items[slot] = value;
            }
            else
            {
                node = (JsonObject)items[slot]!;
            }
        }
    }

    private static string[] ColumnNames(JsonNode resultSet) =>
        [.. resultSet["columns"]!.AsArray().Select(c => (string)c!["name"]!)];

    private static JsonNode? Text(JsonNode? value, string order, MappingReport report) =>
        value is null ? null : JsonValue.Create((string)value!);

    /// <summary>DV_TEXT / DV_CODED_TEXT -> CodeableConcept. Unknown terminologies keep the text and are reported.</summary>
    private static JsonNode? Codeable(JsonNode? value, string order, MappingReport report)
    {
        if (value is null)
        {
            return null;
        }

        string display = (string)value["value"]!;
        JsonObject concept = new() { ["text"] = display };
        JsonNode? code = value["defining_code"];
        if (code is null)
        {
            report.Notes.Add($"{order}: '{display}' is uncoded text");
            return concept;
        }

        string terminology = (string)code["terminology_id"]!["value"]!;
        if (!Terminologies.TryGetValue(terminology, out string? system))
        {
            report.Notes.Add($"{order}: terminology '{terminology}' has no FHIR system; code dropped");
            return concept;
        }

        concept["coding"] = new JsonArray(new JsonObject
        {
            ["system"] = system, ["code"] = (string)code["code_string"]!, ["display"] = display,
        });
        return concept;
    }
}
