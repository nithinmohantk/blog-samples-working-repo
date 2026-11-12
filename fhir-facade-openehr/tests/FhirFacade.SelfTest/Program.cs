using System.Net;
using System.Text.Json.Nodes;
using FhirFacade;
using FhirFacade.Auth;
using FhirFacade.Fhir;
using FhirFacade.OpenEhr;
using FhirFacade.SelfTest;
using Microsoft.AspNetCore.Authentication;
using Microsoft.AspNetCore.Hosting.Server;
using Microsoft.AspNetCore.Hosting.Server.Features;

// Hosts the facade on a loopback port with test authentication and a stub repository, then calls it over HTTP.

int failures = 0, checks = 0;
void Check(bool condition, string what)
{
    checks++;
    if (!condition)
    {
        failures++;
    }

    Console.WriteLine($"{(condition ? "PASS" : "FAIL")}  {what}");
}

// ---- Scope parsing, with no server involved -------------------------------------------------------
Check(SmartScope.TryParse("patient/Observation.rs", out SmartScope? v2) && v2!.Covers("Observation", SmartPermissions.Read | SmartPermissions.Search), "v2 scope patient/Observation.rs grants read and search");
Check(SmartScope.TryParse("patient/Observation.read", out SmartScope? v1) && v1!.Covers("Observation", SmartPermissions.Search) && !v1.Covers("Observation", SmartPermissions.Create), "v1 scope .read grants read and search, not create");
Check(SmartScope.TryParse("patient.all.read", out SmartScope? entra) && entra!.Resource == SmartScope.AnyResource && entra.Covers("Observation", SmartPermissions.Read), "Entra spelling patient.all.read is patient/*.read");
Check(SmartScope.TryParse("system.Observation.rs", out SmartScope? dotted) && dotted!.Context == SmartContext.System, "Entra spelling system.Observation.rs is a system scope");
Check(!SmartScope.TryParse("patient/Observation.rs?category=vital-signs", out _), "a scope with a query constraint is not accepted");
Check(!SmartScope.TryParse("patient/Observation.sr", out _), "permission letters out of order are not accepted");
Check(!SmartScope.TryParse("openid", out _) && !SmartScope.TryParse("patient/Observation.", out _), "non-resource scopes are ignored");
Check(SmartScope.TryParse("patient/Patient.rs", out SmartScope? other) && !other!.Covers("Observation", SmartPermissions.Read), "a scope for another resource type does not cover Observation");

// ---- The facade, hosted for real ------------------------------------------------------------------
StubRepository repository = new(Path.Combine(AppContext.BaseDirectory, "recorded", "blood_pressure_rows.json"));

WebApplicationBuilder builder = WebApplication.CreateBuilder(args);
builder.Logging.SetMinimumLevel(LogLevel.Critical);
builder.WebHost.UseUrls("http://127.0.0.1:0");
builder.Configuration.AddInMemoryCollection(new Dictionary<string, string?>
{
    ["OpenEhr:BaseUrl"] = "http://ehrbase.test/openehr/v1/",
    ["OpenEhr:SubjectNamespace"] = "dataa-demo",
    ["Fhir:PublicBaseUrl"] = "https://facade.example/fhir",
});
builder.Services.AddAuthentication(TestAuthHandler.SchemeName)
    .AddScheme<AuthenticationSchemeOptions, TestAuthHandler>(TestAuthHandler.SchemeName, null);
builder.Services.AddFacade(builder.Configuration);
builder.Services.AddHttpClient<OpenEhrClient>().ConfigurePrimaryHttpMessageHandler(() => repository);

await using WebApplication app = builder.Build();
app.MapFacade();
await app.StartAsync();
string address = app.Services.GetRequiredService<IServer>().Features.Get<IServerAddressesFeature>()!.Addresses.First();
using HttpClient http = new() { BaseAddress = new Uri(address) };

async Task<(HttpStatusCode Status, JsonNode? Body, string? ContentType)> Get(string url, object? claims = null)
{
    using HttpRequestMessage request = new(HttpMethod.Get, url);
    if (claims is not null)
    {
        request.Headers.Add(TestAuthHandler.Header, System.Text.Json.JsonSerializer.Serialize(claims));
    }

    using HttpResponseMessage response = await http.SendAsync(request);
    string text = await response.Content.ReadAsStringAsync();
    return (response.StatusCode, text.Length == 0 ? null : JsonNode.Parse(text), response.Content.Headers.ContentType?.MediaType);
}

object Patient(string id, string scope) => new { sub = "user-" + id, azp = "test-app", scp = scope, fhirUser = $"https://facade.example/fhir/Patient/{id}" };
const string Bp = "code=http://loinc.org%7C85354-9";
string Diagnostics(JsonNode? outcome) => (string?)outcome?["issue"]?[0]?["diagnostics"] ?? "";
bool IsMappingFailure((HttpStatusCode Status, JsonNode? Body, string? ContentType) r) =>
    r.Status == HttpStatusCode.InternalServerError && (string?)r.Body?["issue"]?[0]?["code"] == "processing";

var metadata = await Get("/fhir/metadata");
Check(metadata.Status == HttpStatusCode.OK && (string?)metadata.Body?["fhirVersion"] == "4.0.1" && metadata.ContentType == "application/fhir+json", "metadata is public and is a FHIR R4 CapabilityStatement");

var anonymous = await Get($"/fhir/Observation?patient=p1&{Bp}");
Check(anonymous.Status == HttpStatusCode.Unauthorized && repository.Requests == 0, "search without a token is 401 and never reaches the repository");

var own = await Get($"/fhir/Observation?patient=p1&{Bp}", Patient("p1", "openid patient/Observation.rs"));
JsonArray entries = own.Body?["entry"]?.AsArray() ?? [];
JsonNode? first = entries.Count > 0 ? entries[0]!["resource"] : null;
Check(own.Status == HttpStatusCode.OK && (string?)own.Body?["type"] == "searchset" && entries.Count == 3, "patient p1 reads their own three readings");
Check((string?)first?["effectiveDateTime"] == "2026-11-03T09:42:00Z"
      && (decimal?)first?["component"]?[0]?["valueQuantity"]?["value"] == 142
      && (string?)first?["component"]?[0]?["code"]?["coding"]?[0]?["code"] == "8480-6"
      && (decimal?)first?["component"]?[1]?["valueQuantity"]?["value"] == 88
      && (string?)first?["component"]?[1]?["valueQuantity"]?["code"] == "mm[Hg]"
      && (string?)first?["subject"]?["reference"] == "Patient/p1", "newest first: 142/88 mm[Hg] on 3 November 2026 for Patient/p1");
string firstId = (string?)first?["id"] ?? "";
Check(firstId == "75667c1ba5044974ac7228ef88efd2efcd440ededc1e49948e78ec362cb07ba0"
      && (string?)first?["identifier"]?[0]?["value"] == "cd440ede-dc1e-4994-8e78-ec362cb07ba0::local.ehrbase.org::1"
      && (string?)first?["meta"]?["versionId"] == "1", "logical id is EHR id plus composition id, with the composition uid as identifier");

var entraSpelling = await Get($"/fhir/Observation?patient=Patient/p1&{Bp}", Patient("p1", "patient.Observation.read"));
Check(entraSpelling.Status == HttpStatusCode.OK && entraSpelling.Body?["entry"]?.AsArray().Count == 3, "Entra-style scope and a Patient/p1 reference work the same way");

var otherPatient = await Get($"/fhir/Observation?patient=p2&{Bp}", Patient("p1", "patient/Observation.rs"));
Check(otherPatient.Status == HttpStatusCode.Forbidden && Diagnostics(otherPatient.Body).Contains("different patient"), "patient p1 asking for p2 is 403");

var wrongResource = await Get($"/fhir/Observation?patient=p1&{Bp}", Patient("p1", "patient/Patient.rs launch/patient"));
Check(wrongResource.Status == HttpStatusCode.Forbidden, "a scope for another resource type is 403");

var readOnlyLetter = await Get($"/fhir/Observation?patient=p1&{Bp}", Patient("p1", "patient/Observation.r"));
Check(readOnlyLetter.Status == HttpStatusCode.Forbidden, "v2 scope with r but not s cannot search");

var constrained = await Get($"/fhir/Observation?patient=p1&{Bp}", Patient("p1", "patient/Observation.rs?category=vital-signs"));
Check(constrained.Status == HttpStatusCode.Forbidden, "a query-constrained scope grants nothing");

var noFhirUser = await Get($"/fhir/Observation?patient=p1&{Bp}", new { sub = "u", scp = "patient/Observation.rs" });
Check(noFhirUser.Status == HttpStatusCode.Forbidden && Diagnostics(noFhirUser.Body).Contains("fhirUser"), "a patient scope without a fhirUser claim is 403");

var userScope = await Get($"/fhir/Observation?patient=p1&{Bp}", new { sub = "dr", scp = "user/Observation.rs", fhirUser = "https://facade.example/fhir/Practitioner/dr1" });
Check(userScope.Status == HttpStatusCode.Forbidden && Diagnostics(userScope.Body).Contains("user-level"), "user/ scopes are refused, not treated as access to everyone");

object backend = new { sub = "svc", azp = "backend-service", roles = new[] { "system/Observation.rs" } };
var system = await Get($"/fhir/Observation?patient=p2&{Bp}", backend);
Check(system.Status == HttpStatusCode.OK && system.Body?["entry"]?.AsArray().Count == 2, "a system scope in the roles claim reads p2's two readings");

var unknownPatient = await Get($"/fhir/Observation?patient=nobody&{Bp}", backend);
Check(unknownPatient.Status == HttpStatusCode.OK && unknownPatient.Body?["entry"]?.AsArray().Count == 0, "an unknown patient is an empty searchset");

foreach ((string query, string what) in new[]
{
    ($"patient=p1&{Bp}&_include=Observation:patient", "an unsupported parameter"),
    ($"patient=p1&{Bp}&category=vital-signs", "a real but unimplemented parameter"),
    (Bp, "a missing patient"),
    ("patient=p1", "a missing code"),
    ("patient=p1&code=http://loinc.org%7C4548-4", "a code the server does not hold"),
    ($"patient=p1&{Bp}&date=ge2026-09-01", "a date without time and offset"),
    ($"patient=p1&{Bp}&date=eq2026-09-01T00:00:00Z", "an unsupported date prefix"),
    ($"patient=p1&{Bp}&_sort=code", "an unsupported sort"),
    ($"patient=p1&{Bp}&_count=0", "a zero page size"),
    ($"patient=p1&patient=p2&{Bp}", "a repeated patient"),
})
{
    var bad = await Get("/fhir/Observation?" + query, backend);
    Check(bad.Status == HttpStatusCode.BadRequest && (string?)bad.Body?["resourceType"] == "OperationOutcome", $"{what} is 400 with an OperationOutcome");
}

var page1 = await Get($"/fhir/Observation?patient=p1&{Bp}&_count=2", backend);
string? next = page1.Body?["link"]?.AsArray().FirstOrDefault(l => (string?)l?["relation"] == "next")?["url"]?.GetValue<string>();
Check(page1.Body?["entry"]?.AsArray().Count == 2 && next is not null && next.StartsWith("https://facade.example/fhir/Observation?", StringComparison.Ordinal), "first page of two has a next link on the public address");
var page2 = await Get(new Uri(next ?? "https://x/").PathAndQuery, backend);
Check(page2.Status == HttpStatusCode.OK && page2.Body?["entry"]?.AsArray().Count == 1
      && page2.Body?["link"]?.AsArray().Count == 1
      && (string?)page2.Body?["entry"]?[0]?["resource"]?["effectiveDateTime"] == "2026-03-02T09:10:00Z", "following next gives the last reading and no further link");

var range = await Get($"/fhir/Observation?patient=p1&{Bp}&date=ge2026-03-01T00:00:00Z&date=lt2026-09-01T00:00:00%2B01:00&_sort=date", backend);
JsonArray ranged = range.Body?["entry"]?.AsArray() ?? [];
Check(ranged.Count == 2 && (string?)ranged[0]?["resource"]?["effectiveDateTime"] == "2026-03-02T09:10:00Z"
      && (string?)ranged[1]?["resource"]?["effectiveDateTime"] == "2026-08-14T10:00:00Z", "date range with ascending sort returns March then August");

var read = await Get("/fhir/Observation/" + firstId, Patient("p1", "patient/Observation.r"));
Check(read.Status == HttpStatusCode.OK && JsonNode.DeepEquals(read.Body, first), "read by id returns the same resource as the search, with r alone");

var readOther = await Get("/fhir/Observation/" + firstId, Patient("p2", "patient/Observation.rs"));
Check(readOther.Status == HttpStatusCode.NotFound, "another patient's token reading that id gets 404, not 403");

var readNoScope = await Get("/fhir/Observation/" + firstId, Patient("p1", "patient/Patient.rs"));
Check(readNoScope.Status == HttpStatusCode.Forbidden, "read without an Observation scope is 403");

var readUnknown = await Get("/fhir/Observation/" + new string('0', 64), backend);
var readMalformed = await Get("/fhir/Observation/not-an-id", backend);
Check(readUnknown.Status == HttpStatusCode.NotFound && readMalformed.Status == HttpStatusCode.NotFound, "an unknown id and a malformed id are both 404");

var down = await Get($"/fhir/Observation?patient=repository-down&{Bp}", backend);
Check(down.Status == HttpStatusCode.BadGateway && (string?)down.Body?["resourceType"] == "OperationOutcome"
      && !down.Body!.ToJsonString().Contains("SECRET-BACKEND-DETAIL", StringComparison.Ordinal), "a repository failure is 502 and its message does not leak");

repository.ExtraRows.Add(new JsonArray("11111111-1111-4111-8111-111111111111", "bad-units", "22222222-2222-4222-8222-222222222222::local.ehrbase.org::1", "2026-11-01T08:00:00Z", 18.9, "kPa", 11.7, "kPa"));
var badUnits = await Get($"/fhir/Observation?patient=bad-units&{Bp}", backend);
Check(IsMappingFailure(badUnits), "a reading in kPa fails the request instead of being relabelled as mmHg");

repository.ExtraRows.Clear();
repository.ExtraRows.Add(new JsonArray("11111111-1111-4111-8111-111111111111", "no-zone", "33333333-3333-4333-8333-333333333333::local.ehrbase.org::1", "2026-11-01T08:00:00", 120, "mm[Hg]", 80, "mm[Hg]"));
var noZone = await Get($"/fhir/Observation?patient=no-zone&{Bp}", backend);
Check(IsMappingFailure(noZone), "an event time without an offset fails the request");

repository.ExtraRows.Clear();
repository.ExtraRows.Add(new JsonArray("11111111-1111-4111-8111-111111111111", "p1", "44444444-4444-4444-8444-444444444444::local.ehrbase.org::1", "2026-11-02T08:00:00Z", 120, "mm[Hg]", 80, "mm[Hg]"));
repository.ExtraRows.Add(new JsonArray("11111111-1111-4111-8111-111111111111", "p1", "44444444-4444-4444-8444-444444444444::local.ehrbase.org::1", "2026-11-02T08:05:00Z", 118, "mm[Hg]", 78, "mm[Hg]"));
var twoInOne = await Get($"/fhir/Observation?patient=p1&{Bp}", backend);
Check(IsMappingFailure(twoInOne), "two readings in one composition fail the request instead of sharing an id");

await app.StopAsync();
Console.WriteLine($"\n{checks - failures} of {checks} checks passed");
return failures == 0 ? 0 : 1;
