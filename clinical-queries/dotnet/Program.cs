// Self-checking console test with a stub HTTP handler. No server is contacted. Run: dotnet run
using System.Net;
using System.Text;
using System.Text.Json.Nodes;
using ClinicalQueries;

static void Check(bool condition, string what)
{
    if (!condition)
    {
        throw new InvalidOperationException($"FAILED: {what}");
    }
}

// ---- FHIR search: two pages, an included Patient that must not be returned as a match
List<string> requested = [];
StubHandler fhirHandler = new(request =>
{
    requested.Add(request.RequestUri!.PathAndQuery);
    return request.RequestUri.Query.Contains("page=2")
        ? """{"resourceType":"Bundle","type":"searchset","entry":[{"resource":{"resourceType":"Observation","id":"bp-1"},"search":{"mode":"match"}}]}"""
        : """
          {"resourceType":"Bundle","type":"searchset",
           "link":[{"relation":"self","url":"https://fhir.example/Observation?patient=p1"},
                   {"relation":"next","url":"https://fhir.example/Observation?patient=p1&page=2"}],
           "entry":[{"resource":{"resourceType":"Observation","id":"bp-3"},"search":{"mode":"match"}},
                    {"resource":{"resourceType":"Observation","id":"bp-2"},"search":{"mode":"match"}},
                    {"resource":{"resourceType":"Patient","id":"p1"},"search":{"mode":"include"}}]}
          """;
});
FhirSearchClient fhir = new(new HttpClient(fhirHandler) { BaseAddress = new Uri("https://fhir.example/") });

List<string> ids = [];
await foreach (JsonObject resource in fhir.SearchAsync(
    "Observation?patient=p1&code=http%3A%2F%2Floinc.org%7C85354-9&_sort=-date&_include=Observation:patient"))
{
    ids.Add((string)resource["id"]!);
}

Console.WriteLine($"FHIR search -> {string.Join(", ", ids)} over {requested.Count} requests");
Check(ids.SequenceEqual(["bp-3", "bp-2", "bp-1"]), "matches from both pages, include skipped");
Check(requested.Count == 2 && requested[1].EndsWith("page=2"), "followed the server's next link");

// ---- AQL: parameters sent separately, rows returned by column name
string? sentBody = null;
StubHandler aqlHandler = new(request =>
{
    sentBody = request.Content!.ReadAsStringAsync().GetAwaiter().GetResult();
    return """
           {"q":"...","columns":[{"name":"measured_at","path":"/time/value"},{"name":"systolic","path":"/x"}],
            "rows":[["2026-11-03T09:42:00Z",142],["2026-08-14T10:00:00Z",146]]}
           """;
});
AqlClient aql = new(new HttpClient(aqlHandler) { BaseAddress = new Uri("https://ehr.example/rest/openehr/v1/") });

var rows = await aql.QueryAsync(
    "SELECT ... FROM EHR e CONTAINS OBSERVATION o WHERE e/ehr_id/value = $ehr_id",
    new Dictionary<string, object> { ["ehr_id"] = "7d44b88c-4199-4bad-97dc-d78268e01398" });

Console.WriteLine($"AQL         -> {rows.Count} rows, first systolic {rows[0]["systolic"]}");
JsonNode sent = JsonNode.Parse(sentBody!)!;
Check((string)sent["query_parameters"]!["ehr_id"]! == "7d44b88c-4199-4bad-97dc-d78268e01398", "parameter sent separately");
Check(!((string)sent["q"]!).Contains("7d44b88c"), "value not concatenated into the query text");
Check(rows.Count == 2 && rows[0]["systolic"]!.GetValue<int>() == 142, "rows keyed by column name");

Console.WriteLine("ALL CLIENT TESTS OK (.NET " + Environment.Version + ")");

internal sealed class StubHandler(Func<HttpRequestMessage, string> respond) : HttpMessageHandler
{
    protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken) =>
        Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = new StringContent(respond(request), Encoding.UTF8, "application/json"),
        });
}
