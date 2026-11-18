# FHIR validation as a build gate

Sample for the dataa.dev article "FHIR Validation in CI: Profiles, Terminology and IPS Checks That Fail the Build".

Two validators check the same FHIR R4 resources against the International Patient Summary profiles
(`hl7.fhir.uv.ips` 2.0.0) in a GitHub Actions workflow: the HL7 validator (`validator_cli.jar`) driven by a
Python wrapper, and a .NET 10 console tool on the Firely SDK. The test data includes resources that are broken
on purpose, and the pipeline checks that each of them is refused.

Synthetic data only. Not clinically validated.

| Path | What it is |
| --- | --- |
| `testdata/valid` | Two resources that conform to the IPS profiles |
| `testdata/invalid` | Seven resources, each broken in one way a validator can see without a terminology server |
| `testdata/terminology` | Two resources that only a terminology server can refuse |
| `testdata/expectations.json` | What the gate must say about each file, and why |
| `gate/fhir_gate.py` | `gate` fails the build on any error; `selfcheck` proves the gate against the expectations |
| `firely/FhirGate` | The same check on the Firely .NET SDK |
| `../.github/workflows/fhir-validation.yml` | The pipeline |

## Run

    # HL7 validator: Java 17 or later, Python 3.11 or later, validator_cli.jar in the current folder
    python gate/fhir_gate.py gate --dir testdata/valid --engine hl7 --ig hl7.fhir.uv.ips#2.0.0 --tx n/a
    python gate/fhir_gate.py selfcheck --testdata testdata --engine hl7 --ig hl7.fhir.uv.ips#2.0.0 --tx https://tx.fhir.org

    # Firely SDK: .NET 10 SDK
    dotnet run --project firely/FhirGate -c Release -- \
      --package hl7.fhir.uv.ips@2.0.0 --package hl7.fhir.uv.extensions.r4@5.3.0-ballot-tc1 \
      --out firely.json testdata/*/*.json
    python gate/fhir_gate.py selfcheck --testdata testdata --engine firely --firely-results firely.json

`gate` exits 0 when every resource conforms, 1 when any does not, 2 when the check could not run.

## What was verified

GitHub Actions, `ubuntu-latest`, 12 November 2026, commit `14cdaff`:
<https://github.com/nithinmohantk/blog-samples-working-repo/actions/runs/43221452138>. The outputs of the
latest run are on the `ci-results` branch.

| Check | Result |
| --- | --- |
| HL7 validator 7.0.5, no terminology server | 11 of 11 as expected; the two terminology cases pass (blind spots) |
| HL7 validator 7.0.5, `https://tx.fhir.org` | 11 of 11 as expected; both terminology cases refused |
| Gate on `testdata/valid` | exit 0, 2 of 2 conform |
| Gate on `testdata/invalid` | exit 1, 0 of 7 conform |
| Firely.Fhir.Validation.R4 3.6.0 (SDK 6.8.0), local terminology | 11 of 11 as expected; the two terminology cases pass (blind spots) |

Java 21.0.13 (Temurin), .NET SDK 10.0.404, Python 3.13.

## Findings from getting it to run

* The HL7 validator process returned exit code 0 in every run, including the run where seven resources had
  errors. The wrapper reads the OperationOutcome output and decides from that.
* Without a terminology server neither validator can judge a SNOMED CT code. A code that does not exist and a
  display that belongs to a different concept both passed. The HL7 validator reported only a narrative
  warning for them; the Firely tool reported nothing.
* The Firely package source loads the packages it is given and no others. With only the IPS package listed,
  the IPS Patient profile failed to load because it refers to an extension in `hl7.fhir.uv.extensions.r4`.
  Every broken resource was still "refused", for the wrong reason; only the two valid resources showed the fault.
* `Firely.Fhir.Packages` has to match the SDK generation: 4.9.1 with SDK 6.8.0 failed at run time with a
  missing type; 5.0.2 works.

Not verified: HL7 Europe Base and Core or any national profile set, a private terminology server, bundles and
documents (only single resources were validated), FHIR R5, Azure DevOps or any other CI system.
