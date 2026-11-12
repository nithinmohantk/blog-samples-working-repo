# Clinical coding with structured outputs and a human review step

Sample for the dataa.dev article "Azure OpenAI Structured Outputs for Clinical Coding: Free Text to FHIR Condition
and Observation, with a Human Review Step".

A clinical note goes in. A model is asked for one JSON document whose schema only allows codes from a closed
subset. Ordinary code then checks every item against the note, a reviewer accepts or rejects what is left, and
FHIR R4 Condition, Observation and Provenance resources are written for accepted items only.

Synthetic data only. Not clinically validated. The code subset is a teaching subset, not a clinical value set.

| Path | What it is |
| --- | --- |
| `terminology/coding-subset.json` | The closed set of SNOMED CT and LOINC codes, with displays, units and ranges |
| `fixtures/scenario.json` | Synthetic notes, hand-written responses, review decisions and expected outcomes |
| `src/ClinicalCoding.Core` | Schema builder and lint, response guard, review rules, FHIR mapper. No packages |
| `src/ClinicalCoding.AzureOpenAI` | The model call on the `OpenAI` and `Azure.Identity` packages, and a small CLI |
| `tests/SelfTest` | 32 checks on the core |
| `python/clinical_coding.py` | The same pipeline in Python |
| `python/azure_extractor.py` | The model call on the `openai` and `azure-identity` packages |
| `../.github/workflows/clinical-coding.yml` | The pipeline that produced the results below |

## Run

    dotnet run --project tests/SelfTest -c Release -- .       # .NET 10 SDK
    python python/test_clinical_coding.py                     # Python 3.11 or later, no packages

    # The request that would be sent (schema and instructions). No network.
    dotnet run --project src/ClinicalCoding.AzureOpenAI -- request .
    python python/azure_extractor.py request

    # A live call. Needs an Azure OpenAI deployment and an identity with the Cognitive Services OpenAI User role.
    export AZURE_OPENAI_ENDPOINT=https://<resource>.openai.azure.com AZURE_OPENAI_DEPLOYMENT=<deployment>
    dotnet run --project src/ClinicalCoding.AzureOpenAI -- propose . note.txt

Never send real patient text to a deployment you have not cleared for it.

## What was verified

GitHub Actions, `ubuntu-latest`, 12 November 2026, commit `7d4acf0`:
<https://github.com/nithinmohantk/blog-samples-working-repo/actions/runs/43257519814>. The outputs of the latest
run are on the `ci-results-clinical-coding` branch.

| Check | Result |
| --- | --- |
| Python pipeline tests | 32 of 32 |
| C# self-test, .NET SDK 10.0.404 | 32 of 32 |
| C# Azure OpenAI client builds (OpenAI 2.15.0, Azure.Identity 1.21.0), warnings as errors | built |
| Python Azure OpenAI client imports (openai 3.49.0, azure-identity 1.27.0) | imported |
| Python and C# produce the same schema, request and FHIR Bundle | same |
| HL7 validator 7.0.5 with `https://tx.fhir.org` on the Bundle | conforms: 0 errors, 6 warnings, 8 information |

The first run of the validator failed the Bundle: oxygen saturation was coded with LOINC 59408-5 alone, and the
FHIR vital signs profile requires 2708-6. The subset was corrected. Five of the six warnings are the
best-practice request for narrative.

## Not verified

**No call to Azure OpenAI was made.** The responses in `fixtures/scenario.json` were written by hand in the
shape the schema allows; they are not model output. Nothing here measures how often a model codes a note
correctly. Also not verified: that the service accepts this schema, Microsoft Entra ID authentication, the
Responses API, latency and cost, a review user interface, and posting the Bundle to a FHIR server.
