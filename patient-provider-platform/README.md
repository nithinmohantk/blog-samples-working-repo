# Patient-provider platform: the booking path

Sample for the dataa.dev article "[Reference Architecture: A Patient-Provider Platform over Two EHRs on Azure](https://www.dataa.dev/2025/11/10/case-study-enterprise-healthcare-integration-building-a-hipaa-compliant-patient-provider-platform/)".

The part of a patient-facing platform that is hardest to get right: booking a slot once, and getting that
booking into an EHR that may be slow, down, or asked twice. .NET 8 and Python, FHIR R4.

All data is synthetic. This is a teaching sample, not a clinically validated or certified product.

| Path | What it is |
| --- | --- |
| `src/Booking.Core/BookingLedger.cs` | Books a slot, writes the appointment and the outbox event as one atomic step |
| `src/Booking.Core/OutboxDispatcher.cs` | Delivers outbox events to the EHR, at least once |
| `src/Booking.Core/CircuitBreaker.cs` | Stops calling an EHR that is failing |
| `src/Booking.Core/FhirEhrGateway.cs` | FHIR R4 conditional create of an Appointment |
| `src/Booking.Core/AuditLog.cs` | Who did what to which record; identifiers only |
| `tests/SelfTest` | 20 in-memory checks, plus 3 against a FHIR server when given its URL |
| `python/fhir_drill.py` | Version-aware update and conditional create against a FHIR server |
| `ci.sh` | Runs all of it |

## Run

    dotnet run --project tests/SelfTest -c Release
    docker run -d -p 8080:8080 hapiproject/hapi:v8.0.0
    python python/fhir_drill.py http://127.0.0.1:8080/fhir
    dotnet run --project tests/SelfTest -c Release -- http://127.0.0.1:8080/fhir

## What was verified

GitHub Actions, `ubuntu-latest`, .NET SDK 8.0.428, Python 3.13, HAPI FHIR 8.0.0 (image built 2025-02-24) in
Docker. Outputs of the latest run are on the `ci-results-healthcare` branch.

| Check | Result |
| --- | --- |
| Booking core, in memory | 20 of 20 |
| FHIR drill against HAPI | 8 of 8 |
| C# gateway against HAPI | 3 of 3 (23 of 23 with the in-memory checks) |

Observed on HAPI FHIR 8.0.0:

- Two concurrent `PUT Slot` with the same `If-Match: W/"1"`: one `200`, one `409`.
- A later `PUT` with the stale version: `409`. The FHIR specification gives `412` for this case, so a client
  should treat both as "somebody else got there first".
- `POST Appointment` three times with the same `If-None-Exist`: `201`, `200`, `200`, and one Appointment found.

## What this does not show

- No Azure resource and no commercial EHR was involved. Whether a given EHR accepts an appointment write,
  and through which interaction, has to be established from its own documentation and sandbox.
- The ledger is in memory behind a lock. The comments in `BookingLedger.cs` give the SQL transaction it
  stands for; that transaction was not run here.
- No load or latency figures. Nothing here was measured for performance.
