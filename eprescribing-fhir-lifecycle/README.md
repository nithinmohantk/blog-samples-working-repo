# ePrescribing on FHIR R4: the prescription lifecycle

Sample for the dataa.dev article "[ePrescribing on FHIR R4: The Prescription Lifecycle as Resources and State Transitions](https://www.dataa.dev/2026/02/21/eprescribing-on-fhir-r4-the-prescription-lifecycle-as-resources-and-state-transitions/)".

A prescription modelled as a FHIR `MedicationRequest`, one `Task` that tracks its fulfilment, and a
`MedicationDispense` for each supply. The rules are one pure function; every transition is one FHIR
transaction whose updates carry `If-Match`.

All data is synthetic, and the medication code is from a made-up code system. This is a teaching sample. It
is not clinically validated and is not a conformant implementation of any national ePrescribing specification.

| Path | What it is |
| --- | --- |
| `src/Prescribing.Core/PrescriptionLifecycle.cs` | The rules: prescription, command and time in; refusal or next state out |
| `src/Prescribing.Core/FhirPrescriptionStore.cs` | Loads a prescription from a FHIR R4 server and applies a command as a transaction Bundle |
| `tests/SelfTest` | 35 state and command pairs, invariants, and the scenarios against a server |
| `python/verify_server_state.py` | Reads what the C# run left on the server with plain HTTP, and repeats the claim race |
| `ci.sh` | Runs all of it |

## Run

    dotnet run --project tests/SelfTest -c Release
    docker run -d -p 8081:8080 hapiproject/hapi:v8.0.0
    dotnet run --project tests/SelfTest -c Release -- http://127.0.0.1:8081/fhir ids.json
    python python/verify_server_state.py http://127.0.0.1:8081/fhir ids.json

## What was verified

GitHub Actions, `ubuntu-latest`, .NET 10, Python 3.13, HAPI FHIR 8.0.0 in Docker. Outputs of the latest run
are on the `ci-results-healthcare` branch under `eprescribing-fhir-lifecycle/`.

| Check | Result |
| --- | --- |
| The rules, no server | RULES |
| The same rules through the FHIR server | SERVER |
| Independent check of the server state, from Python | PYTHON |

Scenarios run against the server: two supplies made by two pharmacies; a repeated dispense recognised and
not repeated; two pharmacies claiming at once; release and re-claim; cancellation before a dispense that
was already decided; twenty simultaneous cancel-and-dispense pairs; withdrawal after the first supply;
dispensing refused after the validity period; expiry.

## What this does not show

- No authentication, authorisation, signatures or audit events. A real service needs all four.
- No partial supplies, substitution, controlled-drug rules, owings or reimbursement.
- One FHIR server, HAPI. Transaction and `If-Match` behaviour should be confirmed on the server you use.
- No national profile. The resources are plain R4 with the fields the lifecycle needs.
