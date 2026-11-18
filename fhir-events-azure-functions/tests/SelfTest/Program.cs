using System.Collections.Concurrent;
using System.Text.Json.Nodes;
using FhirEvents.Core;

int failures = 0, checks = 0;
void Check(bool condition, string what)
{
    checks++;
    failures += condition ? 0 : 1;
    Console.WriteLine($"{(condition ? "PASS" : "FAIL")}  {what}");
}

// ---- Parsing ---------------------------------------------------------------------------------------
const string Documented = """
[{
  "id": "e4c7f556-d72c-e7f7-1069-1e82ac76ab41",
  "topic": "/subscriptions/s/resourceGroups/g/providers/Microsoft.HealthcareApis/workspaces/w",
  "subject": "account.fhir.azurehealthcareapis.com/Patient/e0a1f743-1a70-451f-830e-e96477163902",
  "data": {"resourceType": "Patient", "resourceFhirAccount": "account.fhir.azurehealthcareapis.com",
           "resourceFhirId": "e0a1f743-1a70-451f-830e-e96477163902", "resourceVersionId": 1},
  "eventType": "Microsoft.HealthcareApis.FhirResourceCreated",
  "dataVersion": "1", "metadataVersion": "1", "eventTime": "2021-09-08T01:14:04.5613214Z"
}]
""";
var (documented, none) = FhirChangeEvent.ParseDelivery(Documented);
Check(none.Count == 0 && documented.Single() == new FhirChangeEvent("e4c7f556-d72c-e7f7-1069-1e82ac76ab41", ChangeKind.Created, "Patient", "e0a1f743-1a70-451f-830e-e96477163902", 1),
    "the documented Event Grid sample parses");

var (cloud, _) = FhirChangeEvent.ParseDelivery("""{"id":"c1","type":"Microsoft.HealthcareApis.FhirResourceDeleted","source":"/subscriptions/s","data":{"resourceType":"Observation","resourceFhirId":"bp-1","resourceVersionId":"7"}}""");
Check(cloud.Single() is { Kind: ChangeKind.Deleted, Version: 7, ResourceId: "bp-1" }, "a CloudEvents delivery with the version as a string parses");

var (mixed, rejected) = FhirChangeEvent.ParseDelivery("""[{"id":"ok","eventType":"Microsoft.HealthcareApis.FhirResourceUpdated","data":{"resourceType":"Observation","resourceFhirId":"bp-1","resourceVersionId":2}},{"id":"dicom","eventType":"Microsoft.HealthcareApis.DicomImageCreated","data":{}},{"id":"nov","eventType":"Microsoft.HealthcareApis.FhirResourceUpdated","data":{"resourceType":"Observation","resourceFhirId":"bp-1"}},"text"]""");
Check(mixed.Count == 1 && rejected.Count == 3 && rejected[0].StartsWith("dicom:") && rejected[1].StartsWith("nov:"), "other event types and incomplete events are rejected one by one, not the whole delivery");
Check(FhirChangeEvent.ParseDelivery("not json").Rejected.Single() == "delivery is not JSON", "a delivery that is not JSON is rejected");

// ---- The scenario shared with the Python implementation ---------------------------------------------
JsonNode scenario = JsonNode.Parse(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "scenario.json")))!;
FakeFhirServer server = new();
InMemoryStore store = new();
FhirChangeHandler handler = new(server, store);
List<string> outcomes = [];
bool asExpected = true;
foreach (JsonNode? step in scenario["steps"]!.AsArray())
{
    if (step!["server"] is JsonObject state)
    {
        server.Set(state);
        continue;
    }

    JsonObject e = step["event"]!.AsObject();
    Outcome outcome = await handler.HandleAsync(new FhirChangeEvent((string)e["id"]!, Enum.Parse<ChangeKind>((string)e["kind"]!),
        (string?)e["resourceType"] ?? "Observation", (string)e["resourceId"]!, (long)e["version"]!), CancellationToken.None);
    outcomes.Add(outcome.ToString());
    asExpected &= outcome.ToString() == (string)step["expect"]!;
}

Check(asExpected, $"all {outcomes.Count} deliveries in the scenario end as expected");
bool projectionMatches = true;
foreach ((string id, JsonNode? expected) in scenario["expectProjection"]!.AsObject())
{
    ProjectionRow row = store.Rows[("Observation", id)];
    projectionMatches &= row.Version == (long)expected!["version"]! && row.Deleted == (bool)expected["deleted"]!
        && row.Retracted == (bool)expected["retracted"]! && row.Systolic == (decimal?)expected["systolic"];
}

Check(projectionMatches && store.Rows.Count == 3, "the projection ends with three rows at the expected versions");
Check(server.Reads == 5, $"the FHIR server was read {server.Reads} times for 12 Observation deliveries: duplicates and late arrivals cost no read");
File.WriteAllText("outcomes.dotnet.json", new JsonArray([.. outcomes.Select(o => (JsonNode)o)]).ToJsonString());

// ---- A correction keeps the row and removes the values ----------------------------------------------
FakeFhirServer s2 = new();
InMemoryStore st2 = new();
s2.Set(JsonNode.Parse("""{"id":"bp-9","version":2,"status":"entered-in-error","systolic":200,"diastolic":120}""")!.AsObject());
await new FhirChangeHandler(s2, st2).HandleAsync(new FhirChangeEvent("x", ChangeKind.Updated, "Observation", "bp-9", 2), CancellationToken.None);
Check(st2.Rows[("Observation", "bp-9")] is { Retracted: true, Deleted: false, Systolic: null, Diastolic: null, PatientId: "p1" }, "an entered-in-error reading is kept as retracted with its values removed");

// ---- Twenty copies of every event, delivered concurrently in random order ---------------------------
FakeFhirServer s3 = new();
InMemoryStore st3 = new();
FhirChangeHandler h3 = new(s3, st3);
s3.Set(JsonNode.Parse("""{"id":"bp-7","version":6,"status":"final","systolic":131,"diastolic":84}""")!.AsObject());
List<FhirChangeEvent> storm = [.. Enumerable.Range(1, 6).SelectMany(v => Enumerable.Repeat(new FhirChangeEvent($"s{v}", v == 1 ? ChangeKind.Created : ChangeKind.Updated, "Observation", "bp-7", v), 20))];
Random.Shared.Shuffle(System.Runtime.InteropServices.CollectionsMarshal.AsSpan(storm));
Outcome[] results = await Task.WhenAll(storm.Select(e => Task.Run(() => h3.HandleAsync(e, CancellationToken.None))));
Check(st3.Rows[("Observation", "bp-7")] is { Version: 6, Systolic: 131 } && results.Count(r => r == Outcome.Applied) >= 1 && st3.Writes == 1,
    "120 concurrent deliveries leave one row at version 6, written once");

// ---- A transient failure is not swallowed -----------------------------------------------------------
FakeFhirServer s4 = new() { Fail = true };
bool threw = false;
try
{
    await new FhirChangeHandler(s4, new InMemoryStore()).HandleAsync(new FhirChangeEvent("t", ChangeKind.Created, "Observation", "bp-1", 1), CancellationToken.None);
}
catch (HttpRequestException)
{
    threw = true;
}

Check(threw, "a FHIR server failure propagates, so the delivery fails and Event Grid retries it");

Console.WriteLine($"\n{checks - failures} of {checks} checks passed");
return failures == 0 ? 0 : 1;

internal sealed class FakeFhirServer : IFhirReader
{
    private readonly ConcurrentDictionary<string, JsonObject> _current = new();
    private int _reads;

    public bool Fail { get; init; }
    public int Reads => _reads;

    public void Set(JsonObject state) => _current[(string)state["id"]!] = JsonNode.Parse(state.ToJsonString())!.AsObject();

    public Task<FhirReadResult> ReadCurrentAsync(string resourceType, string resourceId, CancellationToken cancellationToken)
    {
        Interlocked.Increment(ref _reads);
        if (Fail)
        {
            throw new HttpRequestException("FHIR server returned HTTP 503");
        }

        if (!_current.TryGetValue(resourceId, out JsonObject? state) || (bool?)state["deleted"] == true)
        {
            return Task.FromResult(FhirReadResult.Gone);
        }

        JsonObject observation = new()
        {
            ["resourceType"] = "Observation",
            ["id"] = resourceId,
            ["status"] = (string)state["status"]!,
            ["subject"] = new JsonObject { ["reference"] = "Patient/p1" },
            ["effectiveDateTime"] = "2026-08-03T09:42:00Z",
            ["component"] = new JsonArray(Component("8480-6", (decimal)state["systolic"]!), Component("8462-4", (decimal)state["diastolic"]!)),
        };
        return Task.FromResult(new FhirReadResult(observation, (long)state["version"]!));
    }

    private static JsonObject Component(string code, decimal value) => new()
    {
        ["code"] = new JsonObject { ["coding"] = new JsonArray(new JsonObject { ["system"] = "http://loinc.org", ["code"] = code }) },
        ["valueQuantity"] = new JsonObject { ["value"] = value, ["unit"] = "mmHg" },
    };
}

/// <summary>Same contract as the PostgreSQL store: the write is conditional on the version and atomic.</summary>
internal sealed class InMemoryStore : IProjectionStore
{
    private readonly Lock _gate = new();
    private int _writes;

    public Dictionary<(string, string), ProjectionRow> Rows { get; } = [];
    public int Writes => _writes;

    public Task<ProjectionRow?> GetAsync(string resourceType, string resourceId, CancellationToken cancellationToken)
    {
        lock (_gate)
        {
            return Task.FromResult(Rows.GetValueOrDefault((resourceType, resourceId)));
        }
    }

    public Task<bool> UpsertIfNewerAsync(ProjectionRow row, CancellationToken cancellationToken)
    {
        lock (_gate)
        {
            if (Rows.TryGetValue((row.ResourceType, row.ResourceId), out ProjectionRow? existing) && existing.Version >= row.Version)
            {
                return Task.FromResult(false);
            }

            Rows[(row.ResourceType, row.ResourceId)] = row;
            _writes++;
            return Task.FromResult(true);
        }
    }
}
