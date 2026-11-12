# openEHR AQL result set to FHIR Bundle

Companion code for "Mapping openEHR Medication Orders to FHIR: AQL In, Transaction Bundle Out" (dataa.dev, September 2026).

A table-driven mapper: an AQL result set of medication orders (archetype
`openEHR-EHR-INSTRUCTION.medication_order.v3`) plus a result set of ACTION states becomes a FHIR R4
transaction Bundle of `MedicationRequest` resources with conditional updates, and a report of every
row rejected or degraded.

| File | Role |
| --- | --- |
| `medication_orders.json`, `medication_actions.json` | Synthetic AQL result sets in the openEHR REST `RESULT_SET` shape |
| `aql_to_fhir.py`, `test_aql_to_fhir.py` | Python mapper and tests |
| `dotnet/MedicationOrderMapper.cs`, `dotnet/Program.cs`, `dotnet/AqlToFhir.csproj` | The same mapper in C# with a self-checking console test |

## Run

    python test_aql_to_fhir.py         # Python 3.11+, no dependencies
    cd dotnet && dotnet run            # .NET 10 SDK, no NuGet packages

Both were run by the author (Python 3.13; the .NET 10 SDK, warnings as errors). The two
implementations produce identical Bundles for the sample input.

## Read before using

* SYNTHETIC DATA ONLY. Do not add real patient data to this repository.
* The result sets were written by hand. The AQL in the article was not executed against an openEHR
  server, and the Bundle was not posted to a FHIR server.
* The instruction-state to `MedicationRequest.status` table is illustrative. It is a clinical decision
  and must be reviewed by clinical modellers before use.
* Not clinically validated. A wrong medication mapping is a patient safety hazard.
