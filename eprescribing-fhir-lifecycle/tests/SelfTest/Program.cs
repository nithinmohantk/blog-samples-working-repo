// dotnet run -c Release                                   the rules only
// dotnet run -c Release -- http://host/fhir ids.json      also runs the scenarios against a FHIR R4 server
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using Prescribing.Core;

int passed = 0, failed = 0;
void Check(string name, bool condition, string detail = "")
{
    if (condition) { passed++; } else { failed++; }
    Console.WriteLine($"{(condition ? "ok  " : "FAIL")}  {name}{(condition || detail.Length == 0 ? "" : $"  [{detail}]")}");
}

const string PharmacyA = "Organization/pharmacy-a", PharmacyB = "Organization/pharmacy-b", Prescriber = "Practitioner/prescriber-1";
DateTimeOffset now = new(2026, 2, 21, 10, 0, 0, TimeSpan.Zero);
Prescription Fresh(int supplies = 2) => new(PrescriptionState.Open, null, supplies, 0, now.AddDays(-1), now.AddDays(180));

// ---- 1. The rules: every state against every command ---------------------------------------------------
Prescription open = Fresh();
Prescription claimed = open with { State = PrescriptionState.Claimed, ClaimedBy = PharmacyA };
(string Name, Prescription Value)[] states =
[
    ("Open", open), ("Claimed by A", claimed),
    ("Completed", open with { State = PrescriptionState.Completed, SuppliesMade = 2 }),
    ("Cancelled", open with { State = PrescriptionState.Cancelled }), ("Expired", open with { State = PrescriptionState.Expired }),
];
(string Name, Command Value)[] commands =
[
    ("Claim by A", new Command.Claim(PharmacyA)), ("Claim by B", new Command.Claim(PharmacyB)), ("Release by A", new Command.Release(PharmacyA)),
    ("Dispense by A", new Command.Dispense(PharmacyA, "d-1")), ("Dispense by B", new Command.Dispense(PharmacyB, "d-2")),
    ("Cancel", new Command.Cancel(Prescriber, "Prescribed in error")), ("Expire", new Command.Expire()),
];
Dictionary<(string, string), string> expected = new()
{
    [("Open", "Claim by A")] = "Claimed", [("Open", "Claim by B")] = "Claimed", [("Open", "Release by A")] = "NotClaimed",
    [("Open", "Dispense by A")] = "NotClaimed", [("Open", "Dispense by B")] = "NotClaimed", [("Open", "Cancel")] = "Cancelled", [("Open", "Expire")] = "NotYetExpired",
    [("Claimed by A", "Claim by A")] = "AlreadyClaimed", [("Claimed by A", "Claim by B")] = "AlreadyClaimed", [("Claimed by A", "Release by A")] = "Open",
    [("Claimed by A", "Dispense by A")] = "Open", [("Claimed by A", "Dispense by B")] = "ClaimedByAnotherPharmacy",
    [("Claimed by A", "Cancel")] = "Cancelled", [("Claimed by A", "Expire")] = "NotYetExpired",
};
Console.WriteLine("state x command -> next state, or the refusal");
int matrixMismatches = 0;
foreach ((string stateName, Prescription state) in states)
{
    foreach ((string commandName, Command command) in commands)
    {
        Decision decision = PrescriptionLifecycle.Decide(state, command, now);
        string actual = decision.Accepted ? decision.Next.State.ToString() : decision.Refusal.ToString();
        string want = expected.GetValueOrDefault((stateName, commandName), "Closed");
        if (actual != want) { matrixMismatches++; }
        Console.WriteLine($"  {stateName,-13} {commandName,-14} {actual}{(actual == want ? "" : $"   expected {want}")}");
    }
}

Check("all 35 state and command pairs give the expected result", matrixMismatches == 0, $"{matrixMismatches} mismatches");
Check("a closed prescription refuses every command", states.Skip(2).All(s => commands.All(c => PrescriptionLifecycle.Decide(s.Value, c.Value, now).Refusal == Refusal.Closed)));
Check("the last authorised supply completes the prescription", PrescriptionLifecycle.Decide(claimed with { SuppliesMade = 1 }, new Command.Dispense(PharmacyA, "d"), now).Next.State == PrescriptionState.Completed);
Check("a dispense clears the claim, so the next supply can come from another pharmacy", PrescriptionLifecycle.Decide(claimed, new Command.Dispense(PharmacyA, "d"), now).Next.ClaimedBy is null);
Check("nothing can be claimed after the validity period", PrescriptionLifecycle.Decide(open, new Command.Claim(PharmacyA), now.AddDays(181)).Refusal == Refusal.OutsideValidityPeriod);
Check("nothing can be dispensed after the validity period, even if claimed in time", PrescriptionLifecycle.Decide(claimed, new Command.Dispense(PharmacyA, "d"), now.AddDays(181)).Refusal == Refusal.OutsideValidityPeriod);
Check("nothing can be claimed before the validity period starts", PrescriptionLifecycle.Decide(open, new Command.Claim(PharmacyA), now.AddDays(-2)).Refusal == Refusal.OutsideValidityPeriod);
Check("expiry applies only once the validity period has ended", PrescriptionLifecycle.Decide(open, new Command.Expire(), now.AddDays(181)).Next.State == PrescriptionState.Expired);
Check("a decision never changes its input", open == Fresh() && claimed.ClaimedBy == PharmacyA);
Check("supplies made never exceed supplies allowed over any sequence", NeverOversupplies());

bool NeverOversupplies()
{
    Random random = new(20260221);
    for (int run = 0; run < 2000; run++)
    {
        Prescription p = Fresh(supplies: 1 + random.Next(3));
        for (int step = 0; step < 40; step++)
        {
            string who = random.Next(2) == 0 ? PharmacyA : PharmacyB;
            Command c = random.Next(4) switch { 0 => new Command.Claim(who), 1 => new Command.Release(who), 2 => new Command.Dispense(who, $"d-{run}-{step}"), _ => new Command.Claim(who) };
            p = PrescriptionLifecycle.Decide(p, c, now).Next;
            if (p.SuppliesMade > p.SuppliesAllowed || (p.State == PrescriptionState.Completed) != (p.SuppliesMade == p.SuppliesAllowed)) { return false; }
        }
    }

    return true;
}

// ---- 2. The same rules through FHIR, against a real server -------------------------------------------------
if (args.Length > 0)
{
    using HttpClient http = new() { BaseAddress = new Uri(args[0].TrimEnd('/') + "/"), Timeout = TimeSpan.FromSeconds(60) };
    MutableClock clock = new(DateTimeOffset.UtcNow);
    FhirPrescriptionStore store = new(http, clock);
    JsonObject ids = [];
    foreach ((string type, string id) in new[] { ("Patient", "synthetic-rx-0042"), ("Practitioner", "prescriber-1"), ("Organization", "pharmacy-a"), ("Organization", "pharmacy-b") })
    {
        await Send(http, HttpMethod.Put, $"{type}/{id}", new JsonObject { ["resourceType"] = type, ["id"] = id, ["active"] = true });
    }

    // Two supplies: A makes the first, B the second.
    string rx1 = await Prescribe(http, clock.GetUtcNow(), repeats: 1, validDays: 180);
    ids["two_supplies"] = rx1;
    LoadedPrescription loaded = await store.LoadAsync(rx1);
    Check("server: a new prescription is open with two supplies allowed", loaded.Prescription is { State: PrescriptionState.Open, SuppliesAllowed: 2, SuppliesMade: 0 });
    Check("server: pharmacy A claims it", (await store.ApplyAsync(loaded, new Command.Claim(PharmacyA))).Outcome == ApplyOutcome.Applied);
    Check("server: pharmacy B cannot dispense what A has claimed", await store.ApplyAsync(await store.LoadAsync(rx1), new Command.Dispense(PharmacyB, "disp-b-wrong")) is { Outcome: ApplyOutcome.Refused, Refusal: Refusal.ClaimedByAnotherPharmacy });
    Check("server: A dispenses the first supply", (await store.ApplyAsync(await store.LoadAsync(rx1), new Command.Dispense(PharmacyA, "disp-rx1-1"))).Outcome == ApplyOutcome.Applied);
    loaded = await store.LoadAsync(rx1);
    Check("server: it is open again with one supply made", loaded.Prescription is { State: PrescriptionState.Open, SuppliesMade: 1, ClaimedBy: null });
    Check("server: the same dispense sent again is recognised, not repeated", (await store.ApplyAsync(loaded, new Command.Dispense(PharmacyA, "disp-rx1-1"))).Outcome == ApplyOutcome.AlreadyApplied);
    await store.ApplyAsync(loaded, new Command.Claim(PharmacyB));
    Check("server: B dispenses the second supply", (await store.ApplyAsync(await store.LoadAsync(rx1), new Command.Dispense(PharmacyB, "disp-rx1-2"))).Outcome == ApplyOutcome.Applied);
    loaded = await store.LoadAsync(rx1);
    Check("server: the prescription is completed with two supplies", loaded.Prescription is { State: PrescriptionState.Completed, SuppliesMade: 2 });
    Check("server: a completed prescription refuses a third claim", await store.ApplyAsync(loaded, new Command.Claim(PharmacyA)) is { Outcome: ApplyOutcome.Refused, Refusal: Refusal.Closed });

    // Two pharmacies read the same open prescription and both try to claim it.
    string rx2 = await Prescribe(http, clock.GetUtcNow(), repeats: 0, validDays: 180);
    ids["claim_race"] = rx2;
    LoadedPrescription seenByA = await store.LoadAsync(rx2), seenByB = await store.LoadAsync(rx2);
    ApplyResult[] race = await Task.WhenAll(store.ApplyAsync(seenByA, new Command.Claim(PharmacyA)), store.ApplyAsync(seenByB, new Command.Claim(PharmacyB)));
    Check("server: of two simultaneous claims, one is applied and one is a conflict", race.Count(r => r.Outcome == ApplyOutcome.Applied) == 1 && race.Count(r => r.Outcome == ApplyOutcome.Conflict) == 1, string.Join(",", race.Select(r => r.Outcome)));
    loaded = await store.LoadAsync(rx2);
    string loser = loaded.Prescription.ClaimedBy == PharmacyA ? PharmacyB : PharmacyA;
    Check("server: the loser reloads and is told it is already claimed", await store.ApplyAsync(loaded, new Command.Claim(loser)) is { Outcome: ApplyOutcome.Refused, Refusal: Refusal.AlreadyClaimed });
    Check("server: the winner releases it and the other pharmacy claims it", (await store.ApplyAsync(loaded, new Command.Release(loaded.Prescription.ClaimedBy!))).Outcome == ApplyOutcome.Applied
        && (await store.ApplyAsync(await store.LoadAsync(rx2), new Command.Claim(loser))).Outcome == ApplyOutcome.Applied);

    // The prescriber cancels while the pharmacy is about to hand the medicine over.
    string rx3 = await Prescribe(http, clock.GetUtcNow(), repeats: 0, validDays: 180);
    ids["cancel_before_dispense"] = rx3;
    await store.ApplyAsync(await store.LoadAsync(rx3), new Command.Claim(PharmacyA));
    LoadedPrescription pharmacyView = await store.LoadAsync(rx3), prescriberView = await store.LoadAsync(rx3);
    Check("server: the prescriber cancels a claimed prescription", (await store.ApplyAsync(prescriberView, new Command.Cancel(Prescriber, "Prescribed in error"))).Outcome == ApplyOutcome.Applied);
    Check("server: the pharmacy's dispense, decided on what it read earlier, is a conflict", (await store.ApplyAsync(pharmacyView, new Command.Dispense(PharmacyA, "disp-rx3-1"))).Outcome == ApplyOutcome.Conflict);
    Check("server: on reloading, the pharmacy is told the prescription is closed", await store.ApplyAsync(await store.LoadAsync(rx3), new Command.Dispense(PharmacyA, "disp-rx3-1")) is { Outcome: ApplyOutcome.Refused, Refusal: Refusal.Closed });
    Check("server: no MedicationDispense exists for the cancelled prescription", await Count(http, $"MedicationDispense?prescription=MedicationRequest/{rx3}") == 0);

    // The same two actions sent at the same instant, twenty times: whichever wins, the record must be coherent.
    int incoherent = 0, cancelWon = 0, dispenseWon = 0;
    JsonArray raced = [];
    for (int i = 0; i < 20; i++)
    {
        string rx = await Prescribe(http, clock.GetUtcNow(), repeats: 0, validDays: 180);
        raced.Add(rx);
        await store.ApplyAsync(await store.LoadAsync(rx), new Command.Claim(PharmacyA));
        LoadedPrescription p = await store.LoadAsync(rx), d = await store.LoadAsync(rx);
        ApplyResult[] both = await Task.WhenAll(store.ApplyAsync(p, new Command.Cancel(Prescriber, "Prescribed in error")), store.ApplyAsync(d, new Command.Dispense(PharmacyA, $"disp-race-{rx}")));
        PrescriptionState end = (await store.LoadAsync(rx)).Prescription.State;
        int dispenses = await Count(http, $"MedicationDispense?prescription=MedicationRequest/{rx}");
        bool coherent = both.Count(r => r.Outcome == ApplyOutcome.Applied) == 1
            && ((end == PrescriptionState.Cancelled && dispenses == 0) || (end == PrescriptionState.Completed && dispenses == 1));
        if (!coherent) { incoherent++; }
        if (end == PrescriptionState.Cancelled) { cancelWon++; } else { dispenseWon++; }
    }

    ids["cancel_dispense_races"] = raced;
    Check("server: 20 simultaneous cancel-and-dispense pairs, each ends cancelled with no dispense or completed with one", incoherent == 0, $"{incoherent} incoherent");
    Console.WriteLine($"      cancel won {cancelWon}, dispense won {dispenseWon}");

    // Withdrawn after the first of two supplies.
    string rx5 = await Prescribe(http, clock.GetUtcNow(), repeats: 1, validDays: 180);
    ids["cancel_after_first_supply"] = rx5;
    await store.ApplyAsync(await store.LoadAsync(rx5), new Command.Claim(PharmacyA));
    await store.ApplyAsync(await store.LoadAsync(rx5), new Command.Dispense(PharmacyA, "disp-rx5-1"));
    Check("server: the prescriber withdraws a prescription after its first supply", (await store.ApplyAsync(await store.LoadAsync(rx5), new Command.Cancel(Prescriber, "Adverse reaction reported"))).Outcome == ApplyOutcome.Applied);
    loaded = await store.LoadAsync(rx5);
    Check("server: it is closed as cancelled, stored as 'stopped' because a supply was made, and the supply stays on record",
        loaded.Prescription is { State: PrescriptionState.Cancelled, SuppliesMade: 1 } && loaded.Request["status"]!.GetValue<string>() == "stopped");

    // Validity period.
    string rx4 = await Prescribe(http, clock.GetUtcNow(), repeats: 1, validDays: 30);
    ids["expired"] = rx4;
    await store.ApplyAsync(await store.LoadAsync(rx4), new Command.Claim(PharmacyA));
    Check("server: expiry is refused while the prescription is valid", await store.ApplyAsync(await store.LoadAsync(rx4), new Command.Expire()) is { Outcome: ApplyOutcome.Refused, Refusal: Refusal.NotYetExpired });
    clock.Advance(TimeSpan.FromDays(31));
    Check("server: after the validity period a claimed prescription cannot be dispensed", await store.ApplyAsync(await store.LoadAsync(rx4), new Command.Dispense(PharmacyA, "disp-rx4-1")) is { Outcome: ApplyOutcome.Refused, Refusal: Refusal.OutsideValidityPeriod });
    Check("server: the housekeeping job expires it", (await store.ApplyAsync(await store.LoadAsync(rx4), new Command.Expire())).Outcome == ApplyOutcome.Applied);
    Check("server: it reads back as expired", (await store.LoadAsync(rx4)).Prescription.State == PrescriptionState.Expired);

    if (args.Length > 1) { File.WriteAllText(args[1], ids.ToJsonString(new JsonSerializerOptions { WriteIndented = true })); }
}

Console.WriteLine($"\n{passed} of {passed + failed} checks passed");
return failed == 0 ? 0 : 1;

// What a prescribing system sends when the prescriber signs: the order and the task that tracks its fulfilment, together.
static async Task<string> Prescribe(HttpClient http, DateTimeOffset signedAt, int repeats, int validDays)
{
    string requestUrn = $"urn:uuid:{Guid.NewGuid()}";
    JsonObject bundle = new()
    {
        ["resourceType"] = "Bundle",
        ["type"] = "transaction",
        ["entry"] = new JsonArray(
            new JsonObject
            {
                ["fullUrl"] = requestUrn,
                ["resource"] = new JsonObject
                {
                    ["resourceType"] = "MedicationRequest",
                    ["identifier"] = new JsonArray(new JsonObject { ["system"] = "https://example.org/fhir/prescription-id", ["value"] = Guid.NewGuid().ToString("N") }),
                    ["status"] = "active",
                    ["intent"] = "order",
                    ["medicationCodeableConcept"] = new JsonObject
                    {
                        ["coding"] = new JsonArray(new JsonObject { ["system"] = "https://example.org/fhir/CodeSystem/synthetic-medication", ["code"] = "amoxicillin-500mg-capsule", ["display"] = "Amoxicillin 500 mg capsules" }),
                        ["text"] = "Amoxicillin 500 mg capsules",
                    },
                    ["subject"] = new JsonObject { ["reference"] = "Patient/synthetic-rx-0042" },
                    ["authoredOn"] = signedAt.ToString("yyyy-MM-ddTHH:mm:ssZ"),
                    ["requester"] = new JsonObject { ["reference"] = "Practitioner/prescriber-1" },
                    ["dosageInstruction"] = new JsonArray(new JsonObject { ["text"] = "One capsule three times a day for seven days" }),
                    ["dispenseRequest"] = new JsonObject
                    {
                        ["validityPeriod"] = new JsonObject { ["start"] = signedAt.ToString("yyyy-MM-ddTHH:mm:ssZ"), ["end"] = signedAt.AddDays(validDays).ToString("yyyy-MM-ddTHH:mm:ssZ") },
                        ["numberOfRepeatsAllowed"] = repeats,
                        ["quantity"] = new JsonObject { ["value"] = 21, ["unit"] = "capsule" },
                    },
                },
                ["request"] = new JsonObject { ["method"] = "POST", ["url"] = "MedicationRequest" },
            },
            new JsonObject
            {
                ["fullUrl"] = $"urn:uuid:{Guid.NewGuid()}",
                ["resource"] = new JsonObject
                {
                    ["resourceType"] = "Task",
                    ["status"] = "requested",
                    ["intent"] = "order",
                    ["code"] = new JsonObject { ["coding"] = new JsonArray(new JsonObject { ["system"] = "http://hl7.org/fhir/CodeSystem/task-code", ["code"] = "fulfill" }) },
                    ["focus"] = new JsonObject { ["reference"] = requestUrn },
                    ["for"] = new JsonObject { ["reference"] = "Patient/synthetic-rx-0042" },
                    ["authoredOn"] = signedAt.ToString("yyyy-MM-ddTHH:mm:ssZ"),
                },
                ["request"] = new JsonObject { ["method"] = "POST", ["url"] = "Task" },
            }),
    };
    JsonObject response = await Send(http, HttpMethod.Post, string.Empty, bundle);
    return response["entry"]![0]!["response"]!["location"]!.GetValue<string>().Split('/')[1];
}

static async Task<JsonObject> Send(HttpClient http, HttpMethod method, string url, JsonObject body)
{
    using HttpRequestMessage request = new(method, url) { Content = new StringContent(body.ToJsonString(), Encoding.UTF8) };
    request.Content.Headers.ContentType = new MediaTypeHeaderValue("application/fhir+json");
    using HttpResponseMessage response = await http.SendAsync(request);
    response.EnsureSuccessStatusCode();
    return JsonNode.Parse(await response.Content.ReadAsStringAsync())!.AsObject();
}

static async Task<int> Count(HttpClient http, string query)
{
    using HttpRequestMessage request = new(HttpMethod.Get, query + "&_summary=count");
    request.Headers.CacheControl = new CacheControlHeaderValue { NoCache = true };
    using HttpResponseMessage response = await http.SendAsync(request);
    return JsonNode.Parse(await response.Content.ReadAsStringAsync())!["total"]!.GetValue<int>();
}

internal sealed class MutableClock(DateTimeOffset start) : TimeProvider
{
    private DateTimeOffset _now = start;
    public override DateTimeOffset GetUtcNow() => _now;
    public void Advance(TimeSpan by) => _now += by;
}
