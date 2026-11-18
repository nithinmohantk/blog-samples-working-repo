using System.Globalization;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using FhirFacade.OpenEhr;

namespace FhirFacade.Fhir;

/// <summary>A row the facade refuses to turn into FHIR. The request fails; nothing is guessed or dropped.</summary>
public sealed class MappingException(string message) : Exception(message);

public static partial class ObservationMapper
{
    public const string CompositionUidSystem = "urn:openehr:composition-uid";
    private const string Loinc = "http://loinc.org";
    private const string Ucum = "http://unitsofmeasure.org";

    [GeneratedRegex(@"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$", RegexOptions.CultureInvariant)]
    private static partial Regex FhirInstant();

    [GeneratedRegex("^[0-9a-f]{64}$", RegexOptions.CultureInvariant)]
    private static partial Regex LogicalId();

    /// <summary>
    /// The FHIR logical id is the EHR id followed by the composition id, both as 32 hexadecimal digits.
    /// That is exactly the 64 characters FHIR allows, and it lets a read find the composition without a search.
    /// </summary>
    public static string ToLogicalId(Guid ehrId, string compositionUid) =>
        ehrId.ToString("N") + Guid.Parse(VersionedObjectId(compositionUid)).ToString("N");

    public static bool TryParseLogicalId(string id, out Guid ehrId, out Guid compositionId)
    {
        ehrId = compositionId = Guid.Empty;
        return LogicalId().IsMatch(id)
            && Guid.TryParseExact(id[..32], "N", out ehrId)
            && Guid.TryParseExact(id[32..], "N", out compositionId);
    }

    public static JsonObject ToObservation(BloodPressureRow row)
    {
        if (!FhirInstant().IsMatch(row.Effective))
        {
            // A time without an offset cannot be placed on a timeline. Refuse it instead of assuming UTC.
            throw new MappingException("event time is not a complete date and time with an offset");
        }

        if (string.IsNullOrEmpty(row.PatientId))
        {
            throw new MappingException("the EHR has no subject identifier, so the reading cannot name a patient");
        }

        JsonArray components = [];
        AddComponent(components, "8480-6", "Systolic blood pressure", row.Systolic, row.SystolicUnits);
        AddComponent(components, "8462-4", "Diastolic blood pressure", row.Diastolic, row.DiastolicUnits);
        if (components.Count == 0)
        {
            throw new MappingException("blood pressure event has neither a systolic nor a diastolic value");
        }

        string[] uidParts = row.CompositionUid.Split("::");
        return new JsonObject
        {
            ["resourceType"] = "Observation",
            ["id"] = ToLogicalId(row.EhrId, row.CompositionUid),
            ["meta"] = new JsonObject { ["versionId"] = uidParts.Length == 3 ? uidParts[2] : "1" },
            // The way back to the source record.
            ["identifier"] = new JsonArray(new JsonObject { ["system"] = CompositionUidSystem, ["value"] = row.CompositionUid }),
            ["status"] = "final",
            ["category"] = new JsonArray(CodeableConcept(
                "http://terminology.hl7.org/CodeSystem/observation-category", "vital-signs", "Vital Signs")),
            ["code"] = CodeableConcept(Loinc, "85354-9", "Blood pressure panel with all children optional"),
            ["subject"] = new JsonObject { ["reference"] = "Patient/" + row.PatientId },
            ["effectiveDateTime"] = row.Effective,
            ["component"] = components,
        };
    }

    /// <summary>Maps a page of rows, refusing a page in which one composition yields more than one reading.</summary>
    public static IReadOnlyList<JsonObject> ToObservations(IEnumerable<BloodPressureRow> rows)
    {
        List<JsonObject> observations = [.. rows.Select(ToObservation)];
        if (observations.Select(o => (string)o["id"]!).Distinct().Count() != observations.Count)
        {
            // The logical id identifies a composition. Two readings in one composition would share an id.
            throw new MappingException("a composition holds more than one blood pressure reading");
        }

        return observations;
    }

    private static void AddComponent(JsonArray components, string code, string display, decimal? value, string? units)
    {
        if (value is null)
        {
            return;
        }

        if (units != "mm[Hg]")
        {
            throw new MappingException(string.Create(CultureInfo.InvariantCulture, $"{display}: expected mm[Hg], got {units ?? "no unit"}"));
        }

        components.Add(new JsonObject
        {
            ["code"] = CodeableConcept(Loinc, code, display),
            ["valueQuantity"] = new JsonObject
            {
                ["value"] = value.Value,
                ["unit"] = "mmHg",
                ["system"] = Ucum,
                ["code"] = "mm[Hg]",
            },
        });
    }

    private static string VersionedObjectId(string compositionUid) => compositionUid.Split("::")[0];

    private static JsonObject CodeableConcept(string system, string code, string display) => new()
    {
        ["coding"] = new JsonArray(new JsonObject { ["system"] = system, ["code"] = code, ["display"] = display }),
    };
}
