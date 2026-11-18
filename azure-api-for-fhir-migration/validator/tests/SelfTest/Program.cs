using System.Net;
using System.Text;
using System.Text.Json.Nodes;
using FhirMigrationValidator;

// Two in-memory FHIR servers behind HttpMessageHandler. Enough of the REST API for the validator: metadata,
// count, a newest-first search and read by id. Synthetic data only.

int failures = 0, checks = 0;
void Check(bool condition, string what)
{
    checks++;
    failures += condition ? 0 : 1;
    Console.WriteLine($"{(condition ? "PASS" : "FAIL")}  {what}");
}

JsonObject Observation(string id, decimal systolic, string updated, string version = "1") => new()
{
    ["resourceType"] = "Observation",
    ["id"] = id,
    ["meta"] = new JsonObject { ["versionId"] = version, ["lastUpdated"] = updated },
    ["status"] = "final",
    ["subject"] = new JsonObject { ["reference"] = "Patient/p1" },
    ["component"] = new JsonArray(new JsonObject { ["valueQuantity"] = new JsonObject { ["value"] = systolic, ["unit"] = "mmHg" } }),
};

FakeFhir Source() => new("4.0.1",
    Observation("bp-1", 150, "2026-03-02T09:10:00Z"),
    Observation("bp-2", 146, "2026-06-14T10:00:00Z", "3"),
    Observation("bp-3", 142, "2026-07-03T09:42:00Z"));

async Task<ValidationReport> Run(FakeFhir source, FakeFhir target, bool compareVersions = false, int sample = 50) =>
    await new MigrationValidator(
            FhirServer.Create("source", new Uri("https://source.example/"), null, source),
            FhirServer.Create("target", new Uri("https://target.example/fhir"), "token", target))
        .RunAsync(new ValidationOptions(["Observation"], sample, compareVersions), CancellationToken.None);

// 1. A faithful copy whose server assigned new versions and timestamps passes by default.
FakeFhir copy = Source();
foreach (JsonObject resource in copy.Resources)
{
    resource["meta"] = new JsonObject { ["versionId"] = "1", ["lastUpdated"] = "2026-08-20T00:00:00Z", ["source"] = "#import" };
}

ValidationReport faithful = await Run(Source(), copy);
Check(faithful.Passed && faithful.Types[0] is { SourceCount: 3, TargetCount: 3, Sampled: 3 }, "a faithful copy passes when versions are not compared");
Check(copy.SawAuthorization && copy.Paths.All(p => p.StartsWith("/fhir/", StringComparison.Ordinal)), "the target token is sent and the base path is kept");
Check(copy.AlwaysNoCache, "every request asks the server not to answer from a cache");

// 2. The same copy fails when history was supposed to be carried across.
ValidationReport versions = await Run(Source(), copy, compareVersions: true);
Check(!versions.Passed && versions.Types[0].Different.TryGetValue("bp-2", out var v) && v.Contains("meta.versionId") && v.Contains("meta.lastUpdated"),
    "with --compare-versions a changed versionId and lastUpdated are reported");

// 3. A missing resource is found by the count and by the sample.
FakeFhir missing = Source();
missing.Resources.RemoveAll(r => (string?)r["id"] == "bp-3");
ValidationReport gap = await Run(Source(), missing);
Check(!gap.Passed && gap.Types[0].TargetCount == 2 && gap.Types[0].MissingOnTarget.SequenceEqual(["bp-3"]), "a resource missing on the target is named");

// 4. A changed value is reported as a path, with no value in the report.
FakeFhir altered = Source();
altered.Resources[2]["component"]![0]!["valueQuantity"]!["value"] = 124;
ValidationReport drift = await Run(Source(), altered);
string driftJson = drift.ToJson().ToJsonString();
Check(!drift.Passed && drift.Types[0].Different["bp-3"].SequenceEqual(["component[0].valueQuantity.value"]), "a changed value is reported by its path");
Check(!driftJson.Contains("124") && !driftJson.Contains("142"), "the report holds paths and ids, never values");

// 5. Number formatting and an extra element.
FakeFhir formatted = Source();
formatted.Resources[0]["component"]![0]!["valueQuantity"]!["value"] = 150.0m;
Check((await Run(Source(), formatted)).Passed, "150 and 150.0 are the same number");
formatted.Resources[0]["note"] = new JsonArray(new JsonObject { ["text"] = "added" });
Check((await Run(Source(), formatted)).Types[0].Different["bp-1"].SequenceEqual(["note (only on target)"]), "an element only the target has is reported");

// 6. Equal counts can hide a swap: one resource missing, one extra.
FakeFhir swapped = Source();
swapped.Resources.RemoveAll(r => (string?)r["id"] == "bp-1");
swapped.Resources.Add(Observation("bp-9", 120, "2026-01-01T00:00:00Z"));
ValidationReport swap = await Run(Source(), swapped);
Check(swap.Types[0].SourceCount == swap.Types[0].TargetCount && !swap.Passed, "equal counts with a different set of ids still fail, through the sample");
Check((await Run(Source(), swapped, sample: 2)).Passed, "a sample that does not reach the missing resource passes: a sample is not proof");

// 7. Different FHIR versions fail even when the data matches.
Check(!(await Run(Source(), new FakeFhir("4.3.0", [.. Source().Resources]))).Passed, "a different FHIR version fails the comparison");

// 8. Throttling is retried; a server error stops the run.
FakeFhir throttled = Source();
throttled.ThrottleNext = 2;
Check((await Run(Source(), throttled)).Passed && throttled.Throttled == 2, "HTTP 429 with Retry-After is retried");
FakeFhir broken = Source();
broken.FailWith = HttpStatusCode.InternalServerError;
bool stopped = false;
try
{
    await Run(Source(), broken);
}
catch (FhirServerException ex)
{
    stopped = ex.Message.Contains("HTTP 500") && !ex.Message.Contains("SECRET");
}

Check(stopped, "a server error stops the run and the message carries no response body");

Console.WriteLine($"\n{checks - failures} of {checks} checks passed");
return failures == 0 ? 0 : 1;

internal sealed class FakeFhir(string fhirVersion, params JsonObject[] resources) : HttpMessageHandler
{
    public List<JsonObject> Resources { get; } = [.. resources];
    public List<string> Paths { get; } = [];
    public bool SawAuthorization { get; private set; }
    public bool AlwaysNoCache { get; private set; } = true;
    public int ThrottleNext { get; set; }
    public int Throttled { get; private set; }
    public HttpStatusCode? FailWith { get; set; }

    protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
    {
        Paths.Add(request.RequestUri!.AbsolutePath);
        SawAuthorization |= request.Headers.Authorization is { Scheme: "Bearer", Parameter: "token" };
        AlwaysNoCache &= request.Headers.CacheControl?.NoCache == true;
        if (request.Method != HttpMethod.Get)
        {
            return Reply(HttpStatusCode.MethodNotAllowed, null);
        }

        if (FailWith is { } failure)
        {
            return Reply(failure, new JsonObject { ["diagnostics"] = "SECRET backend detail" });
        }

        if (ThrottleNext > 0)
        {
            ThrottleNext--;
            Throttled++;
            HttpResponseMessage busy = new(HttpStatusCode.TooManyRequests);
            busy.Headers.TryAddWithoutValidation("Retry-After", "0");
            return Task.FromResult(busy);
        }

        string[] segments = request.RequestUri.AbsolutePath.Split('/', StringSplitOptions.RemoveEmptyEntries);
        string last = segments[^1];
        string query = request.RequestUri.Query;
        if (last == "metadata")
        {
            return Reply(HttpStatusCode.OK, new JsonObject { ["resourceType"] = "CapabilityStatement", ["fhirVersion"] = fhirVersion });
        }

        List<JsonObject> ofType = [.. Resources.Where(r => (string?)r["resourceType"] == last)];
        if (query.Contains("_summary=count"))
        {
            return Reply(HttpStatusCode.OK, new JsonObject { ["resourceType"] = "Bundle", ["total"] = ofType.Count });
        }

        if (query.Contains("_sort=-_lastUpdated"))
        {
            int count = int.Parse(query.Split("_count=")[1].Split('&')[0]);
            return Reply(HttpStatusCode.OK, new JsonObject
            {
                ["resourceType"] = "Bundle",
                ["entry"] = new JsonArray([.. ofType.OrderByDescending(r => (string?)r["meta"]?["lastUpdated"], StringComparer.Ordinal)
                    .Take(count).Select(r => (JsonNode)new JsonObject { ["resource"] = r.DeepClone() })]),
            });
        }

        JsonObject? one = Resources.FirstOrDefault(r => (string?)r["resourceType"] == segments[^2] && (string?)r["id"] == last);
        return Reply(one is null ? HttpStatusCode.NotFound : HttpStatusCode.OK, one?.DeepClone());
    }

    private static Task<HttpResponseMessage> Reply(HttpStatusCode status, JsonNode? body) => Task.FromResult(new HttpResponseMessage(status)
    {
        Content = new StringContent(body?.ToJsonString() ?? "", Encoding.UTF8, "application/fhir+json"),
    });
}
