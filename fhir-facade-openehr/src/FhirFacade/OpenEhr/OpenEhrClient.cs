using System.Net;
using System.Net.Http.Json;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace FhirFacade.OpenEhr;

/// <summary>One row of the blood pressure result set, still in openEHR terms.</summary>
public sealed record BloodPressureRow(
    Guid EhrId, string? PatientId, string CompositionUid, string Effective,
    decimal? Systolic, string? SystolicUnits, decimal? Diastolic, string? DiastolicUnits);

/// <summary>The repository did not answer, or answered with something the facade cannot use.</summary>
public sealed class OpenEhrUnavailableException(string message, Exception? inner = null) : Exception(message, inner);

public sealed class OpenEhrClient(HttpClient http, ILogger<OpenEhrClient> logger)
{
    private static readonly string[] Columns =
    [
        "ehr_id", "patient_id", "composition_uid", "effective",
        "systolic", "systolic_units", "diastolic", "diastolic_units",
    ];

    public async Task<IReadOnlyList<BloodPressureRow>> QueryAsync(AqlQuery query, CancellationToken cancellationToken)
    {
        JsonObject parameters = [];
        foreach ((string name, string value) in query.Parameters)
        {
            parameters[name] = value;
        }

        JsonObject body = new() { ["q"] = query.Text, ["query_parameters"] = parameters };
        JsonNode? result;
        try
        {
            using HttpResponseMessage response = await http.PostAsJsonAsync("query/aql", body, cancellationToken);
            if (!response.IsSuccessStatusCode)
            {
                // The response body can echo the query with parameter values written in. Log the status only.
                logger.LogError("openEHR query failed with HTTP {Status}", (int)response.StatusCode);
                throw new OpenEhrUnavailableException($"openEHR query returned HTTP {(int)response.StatusCode}");
            }

            result = await response.Content.ReadFromJsonAsync<JsonNode>(cancellationToken);
        }
        catch (Exception ex) when (ex is HttpRequestException or JsonException
            || (ex is OperationCanceledException && !cancellationToken.IsCancellationRequested))
        {
            throw new OpenEhrUnavailableException("openEHR query did not complete", ex);
        }

        try
        {
            string[] names = [.. result!["columns"]!.AsArray().Select(column => (string)column!["name"]!)];
            int[] index = [.. Columns.Select(column => Array.IndexOf(names, column))];
            if (index.Contains(-1))
            {
                throw new OpenEhrUnavailableException("openEHR result set is missing an expected column");
            }

            return [.. result["rows"]!.AsArray().Select(row => new BloodPressureRow(
                Guid.Parse((string)row![index[0]]!),
                (string?)row[index[1]],
                (string)row[index[2]]!,
                (string)row[index[3]]!,
                (decimal?)row[index[4]],
                (string?)row[index[5]],
                (decimal?)row[index[6]],
                (string?)row[index[7]]))];
        }
        catch (Exception ex) when (ex is NullReferenceException or InvalidOperationException or FormatException)
        {
            throw new OpenEhrUnavailableException("openEHR result set has an unexpected shape", ex);
        }
    }

    /// <summary>
    /// Returns the full identifier of the latest version of a composition, or null when it does not exist in
    /// that EHR. AQL on EHRbase matches a composition only by its full version identifier, so a lookup by the
    /// version-independent part has to go through the composition endpoint first.
    /// </summary>
    public async Task<string?> LatestVersionUidAsync(Guid ehrId, Guid compositionId, CancellationToken cancellationToken)
    {
        try
        {
            using HttpRequestMessage request = new(HttpMethod.Head, $"ehr/{ehrId:D}/composition/{compositionId:D}");
            using HttpResponseMessage response = await http.SendAsync(request, cancellationToken);
            if (response.StatusCode is HttpStatusCode.NotFound or HttpStatusCode.NoContent)
            {
                return null; // 204 is how the openEHR REST API reports a deleted composition.
            }

            if (!response.IsSuccessStatusCode || response.Headers.ETag is null)
            {
                logger.LogError("openEHR composition lookup failed with HTTP {Status}", (int)response.StatusCode);
                throw new OpenEhrUnavailableException($"openEHR composition lookup returned HTTP {(int)response.StatusCode}");
            }

            return response.Headers.ETag.Tag.Trim('"');
        }
        catch (Exception ex) when (ex is HttpRequestException
            || (ex is OperationCanceledException && !cancellationToken.IsCancellationRequested))
        {
            throw new OpenEhrUnavailableException("openEHR composition lookup did not complete", ex);
        }
    }
}
