using System.Text;
using System.Text.Json.Nodes;

namespace ClinicalCoding.Core;

/// <summary>Builds the JSON Schema sent as the response format, and the instructions that go with it.</summary>
public static class ExtractionSchema
{
    public static readonly string[] Assertions = ["present", "absent", "uncertain", "family_history"];

    private static readonly HashSet<string> UnsupportedKeywords =
    [
        "minLength", "maxLength", "pattern", "format", "minimum", "maximum", "multipleOf", "patternProperties",
        "unevaluatedProperties", "propertyNames", "minProperties", "maxProperties", "unevaluatedItems", "contains",
        "minContains", "maxContains", "minItems", "maxItems", "uniqueItems",
    ];

    /// <summary>The enums are the subset: the model cannot return any other code.</summary>
    public static JsonObject Build(CodingSubset subset)
    {
        string[] units = [.. subset.Observations.Select(o => o.Unit).Distinct().Order(StringComparer.Ordinal), CodingSubset.OtherUnit];
        JsonObject Evidence() => Text("Exact words copied from the note that support this item. No paraphrase.");

        return new JsonObject
        {
            ["type"] = "object",
            ["additionalProperties"] = false,
            ["required"] = Array("conditions", "observations"),
            ["properties"] = new JsonObject
            {
                ["conditions"] = ArrayOf(new JsonObject
                {
                    ["type"] = "object",
                    ["additionalProperties"] = false,
                    ["required"] = Array("evidence", "code", "assertion"),
                    ["properties"] = new JsonObject
                    {
                        ["evidence"] = Evidence(),
                        ["code"] = Enum([.. subset.Conditions.Select(c => c.Code), CodingSubset.Uncoded],
                            "SNOMED CT code from the list in the instructions, or 'uncoded' when none fits."),
                        ["assertion"] = Enum(Assertions,
                            "present: the patient has it. absent: the note rules it out. uncertain: suspected or queried. family_history: about a relative."),
                    },
                }),
                ["observations"] = ArrayOf(new JsonObject
                {
                    ["type"] = "object",
                    ["additionalProperties"] = false,
                    ["required"] = Array("evidence", "code", "value", "unit"),
                    ["properties"] = new JsonObject
                    {
                        ["evidence"] = Evidence(),
                        ["code"] = Enum([.. subset.Observations.Select(o => o.Code)], "LOINC code from the list in the instructions."),
                        ["value"] = new JsonObject { ["type"] = "number", ["description"] = "The number as written in the note. Do not convert units." },
                        ["unit"] = Enum(units, "UCUM unit as written in the note, or 'other' when the note uses a different unit."),
                    },
                }),
            },
        };
    }

    /// <summary>Checks a schema against the documented limits of strict structured outputs.</summary>
    public static IReadOnlyList<string> Lint(JsonObject schema)
    {
        List<string> problems = [];
        int count = 0;
        if (schema["type"]?.GetValue<string>() != "object")
        {
            problems.Add("$: the root must be an object");
        }

        Walk(schema, "$", 1);
        if (count > 100)
        {
            problems.Add($"$: {count} properties, the limit is 100");
        }

        return problems;

        void Walk(JsonObject node, string path, int depth)
        {
            problems.AddRange(node.Select(p => p.Key).Where(UnsupportedKeywords.Contains).Select(k => $"{path}: keyword '{k}' is not supported"));
            string? type = node["type"]?.GetValue<string>();
            if (type == "object")
            {
                if (depth > 5)
                {
                    problems.Add($"{path}: more than five levels of nesting");
                }

                JsonObject properties = node["properties"] as JsonObject ?? [];
                count += properties.Count;
                if (node["additionalProperties"] is not JsonValue additional || !additional.TryGetValue(out bool allowed) || allowed)
                {
                    problems.Add($"{path}: additionalProperties must be false");
                }

                IEnumerable<string> required = (node["required"] as JsonArray ?? []).Select(r => r!.GetValue<string>());
                if (!required.Order(StringComparer.Ordinal).SequenceEqual(properties.Select(p => p.Key).Order(StringComparer.Ordinal)))
                {
                    problems.Add($"{path}: every property must be listed in required");
                }

                foreach ((string name, JsonNode? child) in properties)
                {
                    Walk((JsonObject)child!, $"{path}.{name}", depth + 1);
                }
            }
            else if (type == "array")
            {
                Walk((JsonObject)node["items"]!, $"{path}[]", depth);
            }
        }
    }

    public static string SystemPrompt(CodingSubset subset)
    {
        StringBuilder prompt = new();
        prompt.Append("You extract coded findings from one clinical note for a clinician to review.\n");
        prompt.Append("Return only items the note states. Copy the supporting words exactly into 'evidence'.\n");
        prompt.Append("Use only the codes listed here. If a condition is stated and no code fits, use 'uncoded'.\n");
        prompt.Append("Do not convert units and do not calculate values.\n\nConditions (SNOMED CT):\n");
        foreach (ConditionCode c in subset.Conditions)
        {
            prompt.Append($"  {c.Code}  {c.Display}  ({c.Hint})\n");
        }

        prompt.Append("\nMeasurements (LOINC, with the only unit accepted):");
        foreach (ObservationCode o in subset.Observations)
        {
            prompt.Append($"\n  {o.Code}  {o.Display}  [{o.Unit}]");
        }

        return prompt.ToString();
    }

    private static JsonObject Text(string description) => new() { ["type"] = "string", ["description"] = description };

    private static JsonObject Enum(IEnumerable<string> values, string description) =>
        new() { ["type"] = "string", ["enum"] = Array([.. values]), ["description"] = description };

    private static JsonObject ArrayOf(JsonObject items) => new() { ["type"] = "array", ["items"] = items };

    private static JsonArray Array(params string[] values) => [.. values.Select(v => (JsonNode)v)];
}
