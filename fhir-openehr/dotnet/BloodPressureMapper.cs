using System.Text.Json.Nodes;

namespace Interop;

/// <summary>What the mapping produced and, as important, what it could not carry.</summary>
public sealed record MappingResult(
    IReadOnlyList<JsonObject> Observations, IReadOnlyList<string> Mapped, IReadOnlyList<string> NotCarried);

/// <summary>
/// Maps an openEHR blood pressure OBSERVATION (archetype blood_pressure.v2, canonical JSON)
/// to FHIR R4 Observation resources. Uses only System.Text.Json: no FHIR or openEHR SDK is required.
/// </summary>
public static class BloodPressureMapper
{
    public const string Archetype = "openEHR-EHR-OBSERVATION.blood_pressure.v2";
    private const string Loinc = "http://loinc.org";
    private const string Ucum = "http://unitsofmeasure.org";
    private const string Snomed = "http://snomed.info/sct";

    private static readonly (string Node, string Code, string Display)[] Components =
    [
        ("at0004", "8480-6", "Systolic blood pressure"),
        ("at0005", "8462-4", "Diastolic blood pressure"),
    ];

    // Archetype-local code for Location of measurement -> SNOMED CT body site. Deliberately incomplete.
    private static readonly Dictionary<string, (string Code, string Display)> BodySites = new()
    {
        ["at0025"] = ("368209003", "Right upper arm structure"),
    };

    /// <param name="patientId">Comes from your EHR-to-Patient index, never from the composition.</param>
    public static MappingResult ToFhir(JsonNode composition, string patientId)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(patientId);
        List<JsonObject> observations = [];
        List<string> mapped = [], notCarried = [];
        string uid = Text(composition["uid"]?["value"], "composition uid");

        foreach (JsonNode? entry in composition["content"]?.AsArray() ?? [])
        {
            string? archetype = (string?)entry?["archetype_node_id"];
            if (archetype != Archetype)
            {
                notCarried.Add($"entry {archetype}: no mapping defined");
                continue;
            }

            Dictionary<string, JsonNode> protocol = Items(entry!["protocol"]);
            foreach (JsonNode? ev in entry["data"]?["events"]?.AsArray() ?? [])
            {
                Dictionary<string, JsonNode> values = Items(ev?["data"]);
                JsonArray components = [];
                foreach ((string node, string code, string display) in Components)
                {
                    if (!values.TryGetValue(node, out JsonNode? element))
                    {
                        continue;
                    }

                    string units = Text(element["value"]?["units"], $"{node} units");
                    if (units != "mm[Hg]")
                    {
                        // A unit the mapping does not expect stops the pipeline. It never passes through.
                        throw new InvalidOperationException($"{node}: expected mm[Hg], got {units}");
                    }

                    components.Add(new JsonObject
                    {
                        ["code"] = Coding(Loinc, code, display),
                        ["valueQuantity"] = new JsonObject
                        {
                            ["value"] = element["value"]!["magnitude"]!.GetValue<decimal>(),
                            ["unit"] = "mmHg",
                            ["system"] = Ucum,
                            ["code"] = "mm[Hg]",
                        },
                    });
                    mapped.Add($"{Name(element)} -> component {code}");
                }

                if (components.Count == 0)
                {
                    notCarried.Add("event without systolic or diastolic: skipped");
                    continue;
                }

                JsonObject observation = new()
                {
                    ["resourceType"] = "Observation",
                    ["status"] = "final",
                    // The way back to the source record.
                    ["identifier"] = new JsonArray(new JsonObject
                        { ["system"] = "urn:openehr:composition-uid", ["value"] = uid }),
                    ["category"] = new JsonArray(
                        Coding("http://terminology.hl7.org/CodeSystem/observation-category", "vital-signs", null)),
                    ["code"] = Coding(Loinc, "85354-9", "Blood pressure panel"),
                    ["subject"] = new JsonObject { ["reference"] = $"Patient/{patientId}" },
                    ["effectiveDateTime"] = Text(ev!["time"]?["value"], "event time"),
                    ["component"] = components,
                };

                if (protocol.TryGetValue("at0014", out JsonNode? site))
                {
                    string local = Text(site["value"]?["defining_code"]?["code_string"], "location code");
                    if (BodySites.TryGetValue(local, out (string Code, string Display) snomed))
                    {
                        observation["bodySite"] = Coding(Snomed, snomed.Code, snomed.Display);
                        mapped.Add($"Location of measurement -> bodySite {snomed.Code}");
                    }
                    else
                    {
                        notCarried.Add($"Location of measurement '{(string?)site["value"]?["value"]}': no SNOMED mapping");
                    }
                }

                notCarried.AddRange(values.Where(v => Components.All(c => c.Node != v.Key))
                    .Select(v => $"data/{Name(v.Value)}"));
                notCarried.AddRange(Items(ev["state"]).Values
                    .Select(i => $"state/{Name(i)} = {(string?)i["value"]?["value"]}"));
                notCarried.AddRange(protocol.Where(p => p.Key != "at0014")
                    .Select(p => $"protocol/{Name(p.Value)} = {(string?)p.Value["value"]?["value"]}"));

                observations.Add(observation);
            }
        }

        return new MappingResult(observations, mapped, notCarried);
    }

    private static Dictionary<string, JsonNode> Items(JsonNode? tree) =>
        (tree?["items"]?.AsArray() ?? [])
            .Where(item => item is not null)
            .ToDictionary(item => Text(item!["archetype_node_id"], "archetype_node_id"), item => item!);

    private static string Name(JsonNode element) => (string?)element["name"]?["value"] ?? "unnamed";

    private static string Text(JsonNode? node, string what) =>
        (string?)node ?? throw new InvalidOperationException($"Missing {what}");

    private static JsonObject Coding(string system, string code, string? display)
    {
        JsonObject coding = new() { ["system"] = system, ["code"] = code };
        if (display is not null)
        {
            coding["display"] = display;
        }

        return new JsonObject { ["coding"] = new JsonArray(coding) };
    }
}
