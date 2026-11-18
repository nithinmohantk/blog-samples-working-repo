using System.Globalization;

namespace AdtToFhir.Core;

/// <summary>An HL7 v2 date or date/time, converted to FHIR at the precision the sender gave and no finer.</summary>
public readonly record struct V2Time(string Fhir, DateTimeOffset? Instant, bool OffsetAssumed)
{
    private static readonly string[] DateFormats = ["yyyy", "yyyyMM", "yyyyMMdd"];
    private static readonly string[] TimeFormats = ["yyyyMMddHH", "yyyyMMddHHmm", "yyyyMMddHHmmss"];

    /// <summary>
    /// Returns null when the value is empty or is not a v2 time. A value with a time of day and no offset gets
    /// <paramref name="defaultOffset"/>, because FHIR does not allow a time without one; with no default it is
    /// cut back to the date.
    /// </summary>
    public static V2Time? Parse(string value, TimeSpan? defaultOffset)
    {
        value = value.Trim();
        if (value.Length == 0) { return null; }

        TimeSpan? offset = null;
        int sign = value.LastIndexOfAny(['+', '-']);
        if (sign >= 4)
        {
            string zone = value[(sign + 1)..];
            if (zone.Length != 4 || !zone.All(char.IsAsciiDigit)) { return null; }
            TimeSpan size = new(int.Parse(zone[..2], CultureInfo.InvariantCulture), int.Parse(zone[2..], CultureInfo.InvariantCulture), 0);
            if (size > TimeSpan.FromHours(14)) { return null; }
            offset = value[sign] == '-' ? -size : size;
            value = value[..sign];
        }
        int dot = value.IndexOf('.');
        if (dot >= 0) { value = value[..dot]; }          // fractions of a second are dropped, not rounded
        if (!value.All(char.IsAsciiDigit)) { return null; }

        if (value.Length <= 8)
        {
            if (!DateTime.TryParseExact(value, DateFormats, CultureInfo.InvariantCulture, DateTimeStyles.None, out DateTime date)) { return null; }
            string text = value.Length switch { 4 => $"{date:yyyy}", 6 => $"{date:yyyy-MM}", _ => $"{date:yyyy-MM-dd}" };
            return new V2Time(text, null, false);
        }
        if (!DateTime.TryParseExact(value, TimeFormats, CultureInfo.InvariantCulture, DateTimeStyles.None, out DateTime local)) { return null; }
        if ((offset ?? defaultOffset) is not TimeSpan known)
        {
            return new V2Time($"{local:yyyy-MM-dd}", null, false);
        }
        DateTimeOffset instant = new(local, known);
        return new V2Time(instant.ToString("yyyy-MM-dd'T'HH:mm:sszzz", CultureInfo.InvariantCulture), instant, offset is null);
    }

    /// <summary>The date part only, for elements such as Patient.birthDate that cannot carry a time.</summary>
    public string DateOnly => Fhir.Length > 10 ? Fhir[..10] : Fhir;
}
