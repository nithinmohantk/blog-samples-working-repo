using System.Text.Json.Nodes;

namespace FhirEvents.Core;

/// <summary>The downstream copy of one blood pressure reading, with the source version it was built from.</summary>
public sealed record ProjectionRow(
    string ResourceType, string ResourceId, long Version, bool Deleted, bool Retracted,
    string? PatientId, string? Effective, decimal? Systolic, decimal? Diastolic)
{
    public static ProjectionRow Tombstone(string resourceType, string resourceId, long version) =>
        new(resourceType, resourceId, version, Deleted: true, Retracted: false, null, null, null, null);

    /// <summary>
    /// Builds the row from a FHIR Observation. A reading marked entered-in-error stays in the projection as
    /// retracted, with its values removed, so that downstream systems can undo what they did with it.
    /// </summary>
    public static ProjectionRow FromObservation(JsonObject observation, long version)
    {
        string id = (string?)observation["id"] ?? throw new FormatException("Observation has no id");
        bool retracted = (string?)observation["status"] == "entered-in-error";
        string? patient = ((string?)observation["subject"]?["reference"])?.Split('/').LastOrDefault();
        return new ProjectionRow("Observation", id, version, Deleted: false, retracted, patient,
            retracted ? null : (string?)observation["effectiveDateTime"],
            retracted ? null : Component(observation, "8480-6"),
            retracted ? null : Component(observation, "8462-4"));
    }

    private static decimal? Component(JsonObject observation, string loincCode) =>
        (observation["component"] as JsonArray)?
            .FirstOrDefault(c => (c?["code"]?["coding"] as JsonArray)?.Any(coding => (string?)coding?["code"] == loincCode) == true)?
            ["valueQuantity"]?["value"]?.GetValue<decimal>();
}

public interface IProjectionStore
{
    /// <summary>The row held for this resource, or null when there is none.</summary>
    Task<ProjectionRow?> GetAsync(string resourceType, string resourceId, CancellationToken cancellationToken);

    /// <summary>
    /// Writes the row only if it is newer than what is stored, as one atomic operation.
    /// Returns false when the stored version is the same or higher.
    /// </summary>
    Task<bool> UpsertIfNewerAsync(ProjectionRow row, CancellationToken cancellationToken);
}

/// <summary>The current state of a resource on the FHIR server: the resource and its version, or gone.</summary>
public sealed record FhirReadResult(JsonObject? Resource, long Version)
{
    public static readonly FhirReadResult Gone = new(null, 0);
}

public interface IFhirReader
{
    /// <summary>Reads the current version. Throws on anything other than success, not found or gone.</summary>
    Task<FhirReadResult> ReadCurrentAsync(string resourceType, string resourceId, CancellationToken cancellationToken);
}
