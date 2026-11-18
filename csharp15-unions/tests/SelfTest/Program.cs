// Usage: dotnet run -c Release -- [outcomes.jsonl]
using System.Text;
using System.Text.Json;
using Prescribing;
using Prescribing.Legacy;

int passed = 0, failed = 0;
void Check(string name, bool condition)
{
    if (condition) { passed++; } else { failed++; }
    Console.WriteLine($"{(condition ? "ok  " : "FAIL")}  {name}");
}

bool Throws<T>(Action action) where T : Exception
{
    try { action(); return false; } catch (T) { return true; }
}

DateTimeOffset now = new(2026, 11, 11, 9, 30, 0, TimeSpan.Zero);
Prescription active = new("rx-001", "amoxicillin 500 mg", PrescriptionStatus.Active, AllergyConflict: false, InteractionWith: null);
Prescription cancelled = active with { Id = "rx-002", Status = PrescriptionStatus.Cancelled };
Prescription expired = active with { Id = "rx-003", Status = PrescriptionStatus.Expired };
Prescription allergic = active with { Id = "rx-004", AllergyConflict = true };
Prescription interacting = active with { Id = "rx-005", Medication = "clarithromycin 500 mg", InteractionWith = "simvastatin" };
Prescription[] all = [active, cancelled, expired, allergic, interacting];
DispenseOutcome[] outcomes = [.. all.Select(p => Dispensing.Decide(p, "Main Street Pharmacy", now))];

Check("an active prescription is dispensed", outcomes[0] is Dispensed { Pharmacy: "Main Street Pharmacy" });
Check("a cancelled prescription is rejected with its code", outcomes[1] is Rejected { Code: "cancelled" });
Check("an expired prescription is rejected with its code", outcomes[2] is Rejected { Code: "expired" });
Check("an allergy conflict is rejected", outcomes[3] is Rejected { Code: "allergy" });
Check("an interaction is referred, neither dispensed nor rejected", outcomes[4] is ReferredToPrescriber);

Check("HTTP mapping covers the three cases", outcomes.Select(o => OutcomeHandlers.ToHttp(o).Status).SequenceEqual([200, 422, 422, 422, 202]));
Check("task status mapping", outcomes.Select(OutcomeHandlers.ToTaskStatus).SequenceEqual(["completed", "rejected", "rejected", "rejected", "on-hold"]));
Check("audit line names the case; ToString does not", OutcomeHandlers.ToAuditLine(outcomes[1]) == "rx-002 rejected code=cancelled" && outcomes[1].ToString() == "Prescribing.DispenseOutcome");

// An array element, like a field, starts as the default value.
DispenseOutcome[] slots = new DispenseOutcome[1];
DispenseOutcome empty = slots[0];
Check("a default outcome holds no value", empty.Value is null);
Check("a default outcome is refused at the API boundary", Throws<InvalidOperationException>(() => OutcomeHandlers.ToHttp(empty)));
Check("a default outcome is visible in the audit log", OutcomeHandlers.ToAuditLine(empty) == "no outcome");

Check("two outcomes with equal contents are equal", outcomes[0].Equals(Dispensing.Decide(active, "Main Street Pharmacy", now)));
Check("an outcome does not equal its own case value", !outcomes[0].Equals(outcomes[0].Value));

JsonSerializerOptions web = JsonSerializerOptions.Web;
string json = JsonSerializer.Serialize(outcomes[4], web);
Check("JSON carries the case's own shape, no wrapper", json == """{"prescriptionId":"rx-005","question":"clarithromycin 500 mg interacts with simvastatin. Confirm or change."}""");
Check("every case survives a JSON round trip", outcomes.All(o => JsonSerializer.Deserialize<DispenseOutcome>(JsonSerializer.Serialize(o, web), web).Equals(o)));
Check("JSON with an unknown shape is refused", Throws<JsonException>(() => JsonSerializer.Deserialize<DispenseOutcome>("""{"prescriptionId":"rx-9","status":"lost"}""", web)));
Check("JSON null becomes a default outcome", JsonSerializer.Deserialize<DispenseOutcome>("null", web).Value is null);

Check("legacy: a cancelled prescription surfaces as an exception", Throws<InvalidOperationException>(() => LegacyDispensing.Decide(cancelled, "Main Street Pharmacy", now)));
DispenseResult legacy = LegacyDispensing.Decide(interacting, "Main Street Pharmacy", now);
Check("legacy: a referral is indistinguishable from a rejection by its flag", legacy is { Success: false, RejectionCode: null, Pharmacy: null });

if (args.Length > 0)
{
    async IAsyncEnumerable<DispenseOutcome> Stream()
    {
        foreach (DispenseOutcome outcome in outcomes)
        {
            await Task.Yield();
            yield return outcome;
        }
    }

    await using FileStream file = File.Create(args[0]);
    await JsonSerializer.SerializeAsyncEnumerable(file, Stream(), topLevelValues: true, web, CancellationToken.None);
}

Console.WriteLine($"\n{passed} of {passed + failed} checks passed");
return failed == 0 ? 0 : 1;
