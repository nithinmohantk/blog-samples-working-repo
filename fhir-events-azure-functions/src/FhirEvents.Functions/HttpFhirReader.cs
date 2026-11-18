using System.Net;
using System.Net.Http.Headers;
using System.Text.Json.Nodes;
using FhirEvents.Core;

namespace FhirEvents.Functions;

/// <summary>
/// Reads the current version of a resource from the FHIR server. In Azure the request needs a bearer token
/// for the FHIR service, obtained with the Function App's managed identity; that is left out of this sample,
/// which was run against a local server without authentication.
/// </summary>
public sealed class HttpFhirReader(HttpClient http) : IFhirReader
{
    public async Task<FhirReadResult> ReadCurrentAsync(string resourceType, string resourceId, CancellationToken cancellationToken)
    {
        using HttpRequestMessage request = new(HttpMethod.Get, $"{resourceType}/{Uri.EscapeDataString(resourceId)}");
        request.Headers.Accept.ParseAdd("application/fhir+json");
        // The read must reflect the change the event announced, not a cached copy from before it.
        request.Headers.CacheControl = new CacheControlHeaderValue { NoCache = true };

        using HttpResponseMessage response = await http.SendAsync(request, cancellationToken);
        if (response.StatusCode is HttpStatusCode.NotFound or HttpStatusCode.Gone)
        {
            return FhirReadResult.Gone;
        }

        // Anything else that is not a success throws, the invocation fails and Event Grid delivers again.
        response.EnsureSuccessStatusCode();
        JsonObject resource = JsonNode.Parse(await response.Content.ReadAsStringAsync(cancellationToken)) as JsonObject
            ?? throw new HttpRequestException("The FHIR server did not return a JSON object");
        return long.TryParse((string?)resource["meta"]?["versionId"], out long version)
            ? new FhirReadResult(resource, version)
            : throw new HttpRequestException("The resource has no numeric meta.versionId");
    }
}
