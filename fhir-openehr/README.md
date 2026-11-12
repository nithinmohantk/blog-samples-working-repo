# FHIR and openEHR mapping sample

Companion code for "FHIR and openEHR: When to Use Which, and How They Coexist" (dataa.dev, July 2026).

Maps one openEHR blood pressure OBSERVATION (archetype `openEHR-EHR-OBSERVATION.blood_pressure.v2`,
canonical JSON) to a FHIR R4 Observation, and reports what the FHIR resource could not carry.

| File | Role |
| --- | --- |
| `bp_composition.json` | Synthetic openEHR composition. At-codes checked against the archetype's ADL in CKM |
| `bp_mapping.py`, `test_bp_mapping.py` | Python mapping, reverse mapping and tests |
| `dotnet/BloodPressureMapper.cs`, `dotnet/Program.cs`, `dotnet/BpMapping.csproj` | The same mapping in C# with a self-checking console test |

## Run

    python test_bp_mapping.py          # Python 3.11+, no dependencies
    cd dotnet && dotnet run            # .NET 10 SDK, no NuGet packages

Both were run by the author: Python 3.13, and the .NET 10 SDK with warnings treated as errors.

## Read before using

* SYNTHETIC DATA ONLY. Do not add real patient data to this repository.
* A hand-written mapping for one archetype, to illustrate the problem. It is not a general mapping engine
  and not clinically validated. Real programmes should use a mapping language and engine and have each
  mapping reviewed by clinical modellers.
* Nothing here was run against an openEHR server (EHRbase or other) or a FHIR server. The AQL in the
  article was not executed.
* The SNOMED CT body-site table is deliberately incomplete: unmapped values are reported, not guessed.
