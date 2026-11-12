using System.Globalization;
using System.Text;

namespace Dotnet11Sample;

/// <summary>Deterministic synthetic data: FHIR-shaped heart rate observations as JSON Lines. No real patients.</summary>
public static class Payload
{
    public sealed record Reading(string Id, string Patient, string Taken, int BeatsPerMinute);

    public static IReadOnlyList<Reading> Readings(int count)
    {
        List<Reading> readings = new(count);
        uint state = 20261110;
        DateTime start = new(2026, 11, 1, 8, 0, 0, DateTimeKind.Utc);
        for (int i = 0; i < count; i++)
        {
            state = unchecked(state * 1664525 + 1013904223);
            int patient = (int)(state >> 8) % 250;
            int rate = 55 + (int)(state >> 16) % 60;
            readings.Add(new Reading($"obs-{i:D6}", $"Patient/synthetic-{patient:D4}",
                start.AddMinutes(i * 7).ToString("yyyy-MM-ddTHH:mm:ssZ", CultureInfo.InvariantCulture), rate));
        }

        return readings;
    }

    public static string ToFhirJson(Reading r) =>
        $$$"""{"resourceType":"Observation","id":"{{{r.Id}}}","status":"final","category":[{"coding":[{"system":"http://terminology.hl7.org/CodeSystem/observation-category","code":"vital-signs"}]}],"code":{"coding":[{"system":"http://loinc.org","code":"8867-4","display":"Heart rate"}]},"subject":{"reference":"{{{r.Patient}}}"},"effectiveDateTime":"{{{r.Taken}}}","valueQuantity":{"value":{{{r.BeatsPerMinute}}},"unit":"/min","system":"http://unitsofmeasure.org","code":"/min"}}""";

    public static byte[] JsonLines(int count)
    {
        StringBuilder text = new();
        foreach (Reading reading in Readings(count))
        {
            text.Append(ToFhirJson(reading)).Append('\n');
        }

        return Encoding.UTF8.GetBytes(text.ToString());
    }
}
