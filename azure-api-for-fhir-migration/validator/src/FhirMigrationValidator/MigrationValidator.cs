using System.Text.Json.Nodes;

namespace FhirMigrationValidator;

public sealed record ValidationOptions(
    IReadOnlyList<string> ResourceTypes, int SampleSize, bool CompareVersions);

public sealed record TypeResult(
    string ResourceType, int SourceCount, int TargetCount, int Sampled,
    IReadOnlyList<string> MissingOnTarget, IReadOnlyDictionary<string, IReadOnlyList<string>> Different)
{
    public bool Passed => SourceCount == TargetCount && MissingOnTarget.Count == 0 && Different.Count == 0;
}

public sealed record ValidationReport(
    DateTimeOffset StartedAt, string SourceFhirVersion, string TargetFhirVersion, IReadOnlyList<TypeResult> Types)
{
    public bool Passed => SourceFhirVersion == TargetFhirVersion && Types.All(type => type.Passed);

    public JsonObject ToJson() => new()
    {
        ["startedAt"] = StartedAt.ToString("O"),
        ["passed"] = Passed,
        ["sourceFhirVersion"] = SourceFhirVersion,
        ["targetFhirVersion"] = TargetFhirVersion,
        ["types"] = new JsonArray([.. Types.Select(type => new JsonObject
        {
            ["resourceType"] = type.ResourceType,
            ["passed"] = type.Passed,
            ["sourceCount"] = type.SourceCount,
            ["targetCount"] = type.TargetCount,
            ["sampled"] = type.Sampled,
            ["missingOnTarget"] = new JsonArray([.. type.MissingOnTarget.Select(id => (JsonNode)id)]),
            ["different"] = new JsonObject(type.Different.Select(pair => KeyValuePair.Create(
                pair.Key, (JsonNode?)new JsonArray([.. pair.Value.Select(path => (JsonNode)path)])))),
        })]),
    };
}

/// <summary>
/// Compares a migrated FHIR server with its source: FHIR version, a count per resource type, and a
/// field-by-field comparison of the most recently updated resources of each type.
/// </summary>
public sealed class MigrationValidator(FhirServer source, FhirServer target)
{
    public async Task<ValidationReport> RunAsync(ValidationOptions options, CancellationToken cancellationToken)
    {
        DateTimeOffset startedAt = DateTimeOffset.UtcNow;
        string sourceVersion = await FhirVersionAsync(source, cancellationToken);
        string targetVersion = await FhirVersionAsync(target, cancellationToken);

        IEnumerable<string> ignore = options.CompareVersions
            ? ResourceComparer.ServerAssigned.Where(path => path == "meta.source")
            : ResourceComparer.ServerAssigned;

        List<TypeResult> results = [];
        foreach (string type in options.ResourceTypes)
        {
            int sourceCount = await source.CountAsync(type, cancellationToken);
            int targetCount = await target.CountAsync(type, cancellationToken);

            // The newest resources are the ones an incremental copy is most likely to have missed.
            JsonObject page = await source.GetAsync($"{type}?_sort=-_lastUpdated&_count={options.SampleSize}", cancellationToken)
                ?? throw new FhirServerException($"{source.Name}: search on {type} returned nothing");

            List<string> missing = [];
            Dictionary<string, IReadOnlyList<string>> different = [];
            int sampled = 0;
            foreach (JsonNode? entry in page["entry"]?.AsArray() ?? [])
            {
                if (entry?["resource"] is not JsonObject original || (string?)original["id"] is not { } id)
                {
                    continue;
                }

                sampled++;
                JsonObject? copy = await target.GetAsync($"{type}/{Uri.EscapeDataString(id)}", cancellationToken);
                if (copy is null)
                {
                    missing.Add(id);
                    continue;
                }

                IReadOnlyList<string> paths = ResourceComparer.Differences(original, copy, ignore);
                if (paths.Count > 0)
                {
                    different[id] = paths;
                }
            }

            results.Add(new TypeResult(type, sourceCount, targetCount, sampled, missing, different));
        }

        return new ValidationReport(startedAt, sourceVersion, targetVersion, results);
    }

    private static async Task<string> FhirVersionAsync(FhirServer server, CancellationToken cancellationToken)
    {
        JsonObject capability = await server.GetAsync("metadata", cancellationToken)
            ?? throw new FhirServerException($"{server.Name}: no capability statement");
        return (string?)capability["fhirVersion"]
            ?? throw new FhirServerException($"{server.Name}: capability statement has no fhirVersion");
    }
}
