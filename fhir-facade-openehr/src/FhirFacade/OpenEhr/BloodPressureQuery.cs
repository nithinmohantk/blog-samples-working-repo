using System.Globalization;

namespace FhirFacade.OpenEhr;

/// <summary>An AQL statement and the values that travel beside it as query_parameters.</summary>
public sealed record AqlQuery(string Text, IReadOnlyDictionary<string, string> Parameters);

/// <summary>
/// Builds the two AQL statements the facade issues against archetype blood_pressure.v2.
/// Both were run against EHRbase 2.39.0; see the README for what that repository accepted and rejected.
/// </summary>
public static class BloodPressureQuery
{
    public const string Archetype = "openEHR-EHR-OBSERVATION.blood_pressure.v2";

    private const string Time = "o/data[at0001]/events[at0006]/time/value";
    private const string Data = "o/data[at0001]/events[at0006]/data[at0003]";

    private const string SelectFrom =
        "SELECT e/ehr_id/value AS ehr_id, " +
        "e/ehr_status/subject/external_ref/id/value AS patient_id, " +
        "c/uid/value AS composition_uid, " +
        Time + " AS effective, " +
        Data + "/items[at0004]/value/magnitude AS systolic, " +
        Data + "/items[at0004]/value/units AS systolic_units, " +
        Data + "/items[at0005]/value/magnitude AS diastolic, " +
        Data + "/items[at0005]/value/units AS diastolic_units " +
        "FROM EHR e CONTAINS COMPOSITION c CONTAINS OBSERVATION o[" + Archetype + "]";

    /// <summary>One patient's readings. The patient is matched on the subject recorded in the EHR status.</summary>
    public static AqlQuery Search(
        string patientId, string subjectNamespace, DateTimeOffset? from, DateTimeOffset? before,
        bool newestFirst, int limit, int offset)
    {
        ArgumentOutOfRangeException.ThrowIfLessThan(limit, 1);
        ArgumentOutOfRangeException.ThrowIfNegative(offset);

        Dictionary<string, string> parameters = new()
        {
            ["patient_id"] = patientId,
            ["namespace"] = subjectNamespace,
        };
        string where = " WHERE e/ehr_status/subject/external_ref/id/value = $patient_id" +
                       " AND e/ehr_status/subject/external_ref/namespace = $namespace";
        if (from is not null)
        {
            where += " AND " + Time + " >= $from";
            parameters["from"] = Instant(from.Value);
        }

        if (before is not null)
        {
            where += " AND " + Time + " < $before";
            parameters["before"] = Instant(before.Value);
        }

        // EHRbase rejects a parameter in LIMIT and OFFSET. Both are integers this method has range-checked,
        // so writing them into the text cannot inject anything.
        string page = string.Create(CultureInfo.InvariantCulture, $" LIMIT {limit} OFFSET {offset}");
        // The composition uid breaks ties, so two readings with the same time keep their order between pages.
        string order = " ORDER BY " + Time + (newestFirst ? " DESC" : " ASC") + ", c/uid/value ASC";
        return new AqlQuery(SelectFrom + where + order + page, parameters);
    }

    /// <summary>One composition, addressed by EHR and by the full version identifier.</summary>
    public static AqlQuery ByComposition(Guid ehrId, string compositionVersionUid) => new(
        SelectFrom + " WHERE e/ehr_id/value = $ehr_id AND c/uid/value = $composition_uid",
        new Dictionary<string, string>
        {
            ["ehr_id"] = ehrId.ToString("D"),
            ["composition_uid"] = compositionVersionUid,
        });

    private static string Instant(DateTimeOffset value) =>
        value.ToUniversalTime().ToString("yyyy-MM-dd'T'HH:mm:ss'Z'", CultureInfo.InvariantCulture);
}
