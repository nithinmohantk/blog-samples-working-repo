// dotnet run -c Release                      in-memory checks only
// dotnet run -c Release -- http://host/fhir  also delivers through FhirEhrGateway to a FHIR R4 server
//                                            (expects Patient/synthetic-0042 and Slot/slot-drill-2 to exist)
using System.Text.Json;
using Booking.Core;

int passed = 0, failed = 0;
void Check(string name, bool condition, string detail = "")
{
    if (condition) { passed++; } else { failed++; }
    Console.WriteLine($"{(condition ? "ok  " : "FAIL")}  {name}{(condition || detail.Length == 0 ? "" : $"  [{detail}]")}");
}

ManualClock clock = new(new DateTimeOffset(2025, 11, 10, 9, 0, 0, TimeSpan.Zero));
string[] slots = ["slot-0900", "slot-0930", "slot-1000"];

// 1. One slot, 200 simultaneous patients.
BookingLedger ledger = new(slots, clock);
BookingResult[] race = new BookingResult[200];
Parallel.For(0, race.Length, i => race[i] = ledger.Book("slot-0900", $"Patient/synthetic-{i:D4}", $"key-{i}"));
Check("200 simultaneous requests for one slot: exactly one is booked", race.Count(r => r.Status == BookingStatus.Booked) == 1);
Check("the other 199 are told the slot is taken", race.Count(r => r.Status == BookingStatus.SlotTaken) == 199);
Check("the booking wrote exactly one outbox event", ledger.PendingEvents().Count == 1);

// 2. Retries.
BookingResult first = ledger.Book("slot-0930", "Patient/synthetic-0042", "retry-key");
BookingResult again = ledger.Book("slot-0930", "Patient/synthetic-0042", "retry-key");
Check("a retried request gets its own booking back, not 'taken'", first.Status == BookingStatus.Booked && again == first);
Check("and does not write a second event", ledger.PendingEvents().Count == 2);
Check("an unknown slot is refused", ledger.Book("slot-9999", "Patient/synthetic-0042", "k-unknown").Status == BookingStatus.UnknownSlot);
Check("an empty idempotency key is refused", Throws(() => ledger.Book("slot-1000", "Patient/synthetic-0042", " ")));

// 3. Delivery to an EHR that fails twice and then answers.
AuditLog audit = new(clock);
FakeEhr flaky = new(failuresBeforeSuccess: 2);
CircuitBreaker breaker = new(failureThreshold: 5, openFor: TimeSpan.FromSeconds(60), clock);
OutboxDispatcher dispatcher = new(ledger, flaky, breaker, audit);
DispatchReport pass1 = await dispatcher.DispatchPendingAsync();
DispatchReport pass2 = await dispatcher.DispatchPendingAsync();
Check("events that fail stay in the outbox", pass1 is { Delivered: 0, Failed: 2 } && ledger.PendingEvents().Count == 2);
Check("and are delivered on a later pass", pass2 is { Delivered: 2, Failed: 0 } && ledger.PendingEvents().Count == 0);
Check("the EHR holds each appointment once", flaky.Stored.Count == 2 && flaky.Stored.Values.All(count => count == 1));

// 4. Delivery repeated after the EHR accepted it but the acknowledgement was lost.
BookingLedger ledger2 = new(slots, clock);
ledger2.Book("slot-1000", "Patient/synthetic-0042", "k-1");
FakeEhr losesAck = new(failuresBeforeSuccess: 0) { LoseFirstAcknowledgement = true };
OutboxDispatcher dispatcher2 = new(ledger2, losesAck, new CircuitBreaker(5, TimeSpan.FromSeconds(60), clock), audit);
DispatchReport lost = await dispatcher2.DispatchPendingAsync();
DispatchReport redelivered = await dispatcher2.DispatchPendingAsync();
Check("a lost acknowledgement causes a second delivery", lost.Failed == 1 && redelivered.Delivered == 1 && losesAck.Calls == 2);
Check("which the EHR recognises: still one appointment", losesAck.Stored.Single().Value == 1);

// 5. An EHR that stays down.
BookingLedger ledger3 = new(Enumerable.Range(0, 12).Select(i => $"slot-{i:D2}"), clock);
for (int i = 0; i < 12; i++) { ledger3.Book($"slot-{i:D2}", "Patient/synthetic-0042", $"down-{i}"); }
FakeEhr down = new(failuresBeforeSuccess: int.MaxValue);
CircuitBreaker breaker3 = new(failureThreshold: 5, openFor: TimeSpan.FromSeconds(60), clock);
OutboxDispatcher dispatcher3 = new(ledger3, down, breaker3, audit);
DispatchReport outage = await dispatcher3.DispatchPendingAsync();
Check("after five failures the circuit opens and the EHR is left alone", outage is { Failed: 5, SkippedCircuitOpen: 7 } && down.Calls == 5 && breaker3.State == CircuitState.Open);
Check("patients could still book: all twelve events are waiting", ledger3.PendingEvents().Count == 12);
clock.Advance(TimeSpan.FromSeconds(61));
DispatchReport trial = await dispatcher3.DispatchPendingAsync();
Check("after the cool-down one trial call is made, fails, and the circuit reopens", breaker3.State == CircuitState.Open && down.Calls == 6 && trial is { Failed: 1, SkippedCircuitOpen: 11 });
down.FailuresBeforeSuccess = 0;
clock.Advance(TimeSpan.FromSeconds(61));
DispatchReport recovery = await dispatcher3.DispatchPendingAsync();
Check("when the EHR returns, the backlog drains and the circuit closes", recovery.Delivered == 12 && breaker3.State == CircuitState.Closed && ledger3.PendingEvents().Count == 0);

// 6. Audit and payload.
Check("the audit trail records every delivery attempt", audit.Entries.Count(e => e.Action == "ehr.appointment.failed") == 9 && audit.Entries.Count(e => e.Action == "ehr.appointment.created") == 14
    && audit.Entries.Count(e => e.Action == "ehr.appointment.already-present") == 1);
Check("audit entries carry identifiers only", audit.Entries.All(e => !e.ResourceId.Contains("Patient/") && e.ResourceId.StartsWith("appt-", StringComparison.Ordinal)));
string fhir = FhirEhrGateway.ToFhir(new AppointmentEvent("appt-000001", "slot-0900", "Patient/synthetic-0042", clock.GetUtcNow()), "https://example.org/platform/appointment-id").ToJsonString();
using (JsonDocument doc = JsonDocument.Parse(fhir))
{
    JsonElement root = doc.RootElement;
    Check("the FHIR Appointment is booked, references the slot and the patient, and carries the business identifier",
        root.GetProperty("resourceType").GetString() == "Appointment" && root.GetProperty("status").GetString() == "booked"
        && root.GetProperty("slot")[0].GetProperty("reference").GetString() == "Slot/slot-0900"
        && root.GetProperty("participant")[0].GetProperty("actor").GetProperty("reference").GetString() == "Patient/synthetic-0042"
        && root.GetProperty("identifier")[0].GetProperty("value").GetString() == "appt-000001");
    Check("and contains no name, birth date or contact detail", !fhir.Contains("name") && !fhir.Contains("birthDate") && !fhir.Contains("telecom"));
}

// 7. Optional: the real gateway against a FHIR R4 server.
if (args.Length > 0)
{
    using HttpClient http = new() { BaseAddress = new Uri(args[0].TrimEnd('/') + "/"), Timeout = TimeSpan.FromSeconds(30) };
    FhirEhrGateway gateway = new(http, "https://example.org/platform/appointment-id");
    AppointmentEvent appointment = new($"appt-{Guid.NewGuid():N}", "slot-drill-2", "Patient/synthetic-0042", DateTimeOffset.UtcNow);
    EhrOutcome one = await gateway.RecordAppointmentAsync(appointment, CancellationToken.None);
    EhrOutcome two = await gateway.RecordAppointmentAsync(appointment, CancellationToken.None);
    Check("FHIR server: the first delivery creates the Appointment", one.Created && one.EhrAppointmentId.Length > 0, $"{one}");
    Check("FHIR server: the second delivery of the same event creates nothing and returns the same id", !two.Created && two.EhrAppointmentId == one.EhrAppointmentId, $"{one} {two}");
    using JsonDocument search = JsonDocument.Parse(await http.GetStringAsync($"Appointment?identifier={Uri.EscapeDataString("https://example.org/platform/appointment-id")}|{appointment.AppointmentId}&_summary=count"));
    Check("FHIR server: a search by the business identifier finds one Appointment", search.RootElement.GetProperty("total").GetInt32() == 1);
}

Console.WriteLine($"\n{passed} of {passed + failed} checks passed");
return failed == 0 ? 0 : 1;

static bool Throws(Action action) { try { action(); return false; } catch (ArgumentException) { return true; } }

internal sealed class ManualClock(DateTimeOffset start) : TimeProvider
{
    private DateTimeOffset _now = start;
    public override DateTimeOffset GetUtcNow() => _now;
    public void Advance(TimeSpan by) => _now += by;
}

/// <summary>An EHR stand-in that deduplicates on the appointment id, as a conditional create does.</summary>
internal sealed class FakeEhr(int failuresBeforeSuccess) : IEhrGateway
{
    public int FailuresBeforeSuccess { get; set; } = failuresBeforeSuccess;
    public bool LoseFirstAcknowledgement { get; set; }
    public int Calls { get; private set; }
    public Dictionary<string, int> Stored { get; } = [];

    public Task<EhrOutcome> RecordAppointmentAsync(AppointmentEvent appointment, CancellationToken cancellationToken)
    {
        Calls++;
        if (FailuresBeforeSuccess > 0)
        {
            FailuresBeforeSuccess--;
            throw new HttpRequestException("EHR unavailable");
        }

        bool created = Stored.TryAdd(appointment.AppointmentId, 1);
        if (LoseFirstAcknowledgement)
        {
            LoseFirstAcknowledgement = false;
            throw new TimeoutException("the EHR stored the appointment and the response was lost");
        }

        return Task.FromResult(new EhrOutcome(created, "ehr-" + appointment.AppointmentId));
    }
}
