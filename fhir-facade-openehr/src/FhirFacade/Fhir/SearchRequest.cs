using System.Globalization;
using System.Text.RegularExpressions;
using Microsoft.Extensions.Primitives;

namespace FhirFacade.Fhir;

/// <summary>
/// The Observation search this facade supports, parsed strictly. A parameter the facade does not implement
/// is an error, because a search that silently ignores a filter returns more than the client asked for.
/// </summary>
public sealed partial record SearchRequest(
    string PatientId, DateTimeOffset? From, DateTimeOffset? Before, bool NewestFirst, int Count, int Offset)
{
    public const string BloodPressureCode = "85354-9";
    private static readonly string[] AcceptedCodes = [BloodPressureCode, "http://loinc.org|" + BloodPressureCode];
    private static readonly HashSet<string> Supported = ["patient", "code", "date", "_sort", "_count", "_offset"];

    [GeneratedRegex(@"^(?:Patient/)?(?<id>[A-Za-z0-9\-\.]{1,64})$", RegexOptions.CultureInvariant)]
    private static partial Regex PatientParameter();

    [GeneratedRegex(@"^(?<prefix>ge|lt)(?<instant>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:Z|[+-]\d{2}:\d{2}))$", RegexOptions.CultureInvariant)]
    private static partial Regex DateParameter();

    public static bool TryParse(IQueryCollection query, FhirOptions options, out SearchRequest? request, out string error)
    {
        request = null;
        string? unsupported = query.Keys.FirstOrDefault(key => !Supported.Contains(key));
        if (unsupported is not null)
        {
            error = $"Search parameter '{unsupported}' is not supported. Supported: {string.Join(", ", Supported.Order(StringComparer.Ordinal))}.";
            return false;
        }

        if (query.Any(pair => pair.Key != "date" && pair.Value.Count > 1))
        {
            error = "Only 'date' may be repeated.";
            return false;
        }

        Match patient = PatientParameter().Match(query["patient"].ToString());
        if (!patient.Success)
        {
            error = "Parameter 'patient' is required and must be a Patient id or a Patient/{id} reference.";
            return false;
        }

        if (!AcceptedCodes.Contains(query["code"].ToString()))
        {
            error = $"Parameter 'code' is required. This server only holds http://loinc.org|{BloodPressureCode}.";
            return false;
        }

        DateTimeOffset? from = null, before = null;
        StringValues dates = query["date"];
        foreach (string? value in dates)
        {
            Match date = DateParameter().Match(value ?? "");
            if (!date.Success)
            {
                error = "Parameter 'date' must be ge or lt followed by a date and time with an offset, " +
                        "for example ge2026-09-01T00:00:00Z. A date without an offset is ambiguous and is refused.";
                return false;
            }

            DateTimeOffset instant = DateTimeOffset.Parse(date.Groups["instant"].Value, CultureInfo.InvariantCulture);
            bool isFrom = date.Groups["prefix"].Value == "ge";
            if ((isFrom ? from : before) is not null)
            {
                error = "Parameter 'date' may appear once with ge and once with lt.";
                return false;
            }

            if (isFrom)
            {
                from = instant;
            }
            else
            {
                before = instant;
            }
        }

        string sort = query.TryGetValue("_sort", out StringValues sortValue) ? sortValue.ToString() : "-date";
        if (sort is not ("date" or "-date"))
        {
            error = "Parameter '_sort' must be date or -date.";
            return false;
        }

        int count = options.DefaultPageSize, offset = 0;
        if ((query.ContainsKey("_count") && (!TryInteger(query["_count"], out count) || count < 1))
            || (query.ContainsKey("_offset") && (!TryInteger(query["_offset"], out offset) || offset < 0)))
        {
            error = "Parameters '_count' and '_offset' must be whole numbers, with _count at least 1.";
            return false;
        }

        error = "";
        request = new SearchRequest(
            patient.Groups["id"].Value, from, before, sort == "-date", Math.Min(count, options.MaxPageSize), offset);
        return true;
    }

    /// <summary>The query string for this search at another offset, used for the self and next links.</summary>
    public string ToQueryString(int offset)
    {
        List<string> parts =
        [
            "patient=" + Uri.EscapeDataString(PatientId),
            "code=" + Uri.EscapeDataString("http://loinc.org|" + BloodPressureCode),
        ];
        if (From is not null)
        {
            parts.Add("date=" + Uri.EscapeDataString("ge" + Instant(From.Value)));
        }

        if (Before is not null)
        {
            parts.Add("date=" + Uri.EscapeDataString("lt" + Instant(Before.Value)));
        }

        parts.Add("_sort=" + (NewestFirst ? "-date" : "date"));
        parts.Add("_count=" + Count.ToString(CultureInfo.InvariantCulture));
        parts.Add("_offset=" + offset.ToString(CultureInfo.InvariantCulture));
        return string.Join('&', parts);
    }

    private static bool TryInteger(StringValues value, out int result) =>
        int.TryParse(value.ToString(), NumberStyles.None, CultureInfo.InvariantCulture, out result);

    private static string Instant(DateTimeOffset value) =>
        value.ToUniversalTime().ToString("yyyy-MM-dd'T'HH:mm:ss'Z'", CultureInfo.InvariantCulture);
}
