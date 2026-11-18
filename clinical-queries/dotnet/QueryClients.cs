using System.Net.Http.Json;
using System.Runtime.CompilerServices;
using System.Text.Json.Nodes;

namespace ClinicalQueries;

/// <summary>Runs a FHIR search and follows the server's paging links until the result is exhausted.</summary>
public sealed class FhirSearchClient(HttpClient http)
{
    /// <param name="query">Resource type and parameters, for example "Observation?patient=p1&amp;_count=50".</param>
    public async IAsyncEnumerable<JsonObject> SearchAsync(
        string query, [EnumeratorCancellation] CancellationToken cancellationToken = default)
    {
        Uri? next = new(query, UriKind.Relative);
        while (next is not null)
        {
            using HttpRequestMessage request = new(HttpMethod.Get, next);
            request.Headers.Accept.ParseAdd("application/fhir+json");
            using HttpResponseMessage response = await http.SendAsync(request, cancellationToken);
            response.EnsureSuccessStatusCode();

            JsonNode bundle = await response.Content.ReadFromJsonAsync<JsonNode>(cancellationToken)
                ?? throw new InvalidOperationException("Empty search response");

            foreach (JsonNode? entry in bundle["entry"]?.AsArray() ?? [])
            {
                // Included resources and OperationOutcome entries are not matches.
                if ((string?)entry?["search"]?["mode"] is null or "match" && entry?["resource"] is JsonObject resource)
                {
                    yield return resource;
                }
            }

            // The server decides the page size and the shape of the next link. Never build it yourself.
            string? link = bundle["link"]?.AsArray()
                .FirstOrDefault(l => (string?)l?["relation"] == "next")?["url"]?.GetValue<string>();
            next = link is null ? null : new Uri(link, UriKind.RelativeOrAbsolute);
        }
    }
}

/// <summary>Runs an ad-hoc AQL query through the openEHR REST API and returns rows keyed by column name.</summary>
public sealed class AqlClient(HttpClient http)
{
    public async Task<IReadOnlyList<IReadOnlyDictionary<string, JsonNode?>>> QueryAsync(
        string aql, IReadOnlyDictionary<string, object> parameters, CancellationToken cancellationToken = default)
    {
        // Values travel as query_parameters. Never concatenate them into the AQL text.
        JsonObject body = new() { ["q"] = aql, ["query_parameters"] = new JsonObject(
            parameters.Select(p => KeyValuePair.Create(p.Key, (JsonNode?)JsonValue.Create(p.Value)))) };

        using HttpResponseMessage response = await http.PostAsJsonAsync("query/aql", body, cancellationToken);
        response.EnsureSuccessStatusCode();

        JsonNode result = await response.Content.ReadFromJsonAsync<JsonNode>(cancellationToken)
            ?? throw new InvalidOperationException("Empty query response");
        string[] names = [.. result["columns"]!.AsArray().Select(c => (string)c!["name"]!)];

        return [.. result["rows"]!.AsArray().Select(row =>
            (IReadOnlyDictionary<string, JsonNode?>)names.Zip(row!.AsArray()).ToDictionary(p => p.First, p => p.Second))];
    }
}
