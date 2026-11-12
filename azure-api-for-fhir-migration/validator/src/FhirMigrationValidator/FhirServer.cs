using System.Net;
using System.Net.Http.Headers;
using System.Text.Json.Nodes;

namespace FhirMigrationValidator;

/// <summary>A read-only view of one FHIR server. It never sends anything but GET.</summary>
public sealed class FhirServer(HttpClient http, string name)
{
    private const int MaxAttempts = 5;

    public string Name { get; } = name;

    public static FhirServer Create(string name, Uri baseUrl, string? bearerToken, HttpMessageHandler? handler = null)
    {
        HttpClient http = handler is null ? new HttpClient() : new HttpClient(handler, disposeHandler: false);
        // A trailing slash keeps relative requests under the base path.
        http.BaseAddress = new Uri(baseUrl.ToString().TrimEnd('/') + "/");
        http.Timeout = TimeSpan.FromSeconds(100);
        http.DefaultRequestHeaders.Accept.ParseAdd("application/fhir+json");
        if (!string.IsNullOrEmpty(bearerToken))
        {
            http.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Bearer", bearerToken);
        }

        return new FhirServer(http, name);
    }

    /// <summary>Returns the resource, or null when the server answers 404 or 410.</summary>
    public async Task<JsonObject?> GetAsync(string relativeUrl, CancellationToken cancellationToken)
    {
        for (int attempt = 1; ; attempt++)
        {
            using HttpResponseMessage response = await http.GetAsync(relativeUrl, cancellationToken);
            if (response.StatusCode is HttpStatusCode.NotFound or HttpStatusCode.Gone)
            {
                return null;
            }

            // Both Azure services throttle with 429. Wait as told, a bounded number of times.
            bool retryable = response.StatusCode is HttpStatusCode.TooManyRequests or HttpStatusCode.ServiceUnavailable;
            if (retryable && attempt < MaxAttempts)
            {
                TimeSpan wait = response.Headers.RetryAfter?.Delta ?? TimeSpan.FromSeconds(Math.Pow(2, attempt));
                await Task.Delay(wait > TimeSpan.FromSeconds(60) ? TimeSpan.FromSeconds(60) : wait, cancellationToken);
                continue;
            }

            if (!response.IsSuccessStatusCode)
            {
                throw new FhirServerException($"{Name}: GET {relativeUrl} returned HTTP {(int)response.StatusCode}");
            }

            string body = await response.Content.ReadAsStringAsync(cancellationToken);
            return JsonNode.Parse(body) as JsonObject
                ?? throw new FhirServerException($"{Name}: GET {relativeUrl} did not return a JSON object");
        }
    }

    public async Task<int> CountAsync(string resourceType, CancellationToken cancellationToken)
    {
        JsonObject bundle = await GetAsync($"{resourceType}?_summary=count", cancellationToken)
            ?? throw new FhirServerException($"{Name}: {resourceType} is not a known resource type");
        return (int?)bundle["total"]
            ?? throw new FhirServerException($"{Name}: count for {resourceType} has no total");
    }
}

public sealed class FhirServerException(string message) : Exception(message);
