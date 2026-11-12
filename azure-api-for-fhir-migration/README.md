# Migrating from Azure API for FHIR to the Azure Health Data Services FHIR service

Sample for the dataa.dev article of the same name.

| Folder | What it is |
| --- | --- |
| `scripts/migrate.py` | Python: `$export` on the source, build the `$import` request from the manifest, `$import` on the target, summarise |
| `scripts/test_migrate.py` | 16 checks against a local stand-in that implements the documented request and response shapes |
| `validator/` | C# console tool (.NET 10, no packages): compares source and target by FHIR version, count per type and a field-by-field sample |
| `validator/tests/SelfTest` | 14 checks with two in-memory FHIR servers |
| `docker-compose.yml` | Rehearsal of the validator against two real FHIR servers (HAPI) |

Synthetic data only. Not clinically validated.

## Run

    python scripts/test_migrate.py                    # Python 3.11+, pip install -r scripts/requirements.txt
    cd validator/tests/SelfTest && dotnet run         # .NET 10 SDK

    # Against Azure (you need FHIR Data Exporter on the source and FHIR Data Importer on the target):
    az login
    python scripts/migrate.py --source https://<name>.azurehealthcareapis.com \
        --target https://<workspace>-<fhir>.fhir.azurehealthcareapis.com \
        --container migration --till 2026-08-22T22:00:00Z --history --deleted

    $env:SOURCE_TOKEN = az account get-access-token --resource https://<name>.azurehealthcareapis.com --query accessToken -o tsv
    $env:TARGET_TOKEN = az account get-access-token --resource https://<workspace>-<fhir>.fhir.azurehealthcareapis.com --query accessToken -o tsv
    dotnet run --project validator/src/FhirMigrationValidator -- --source <source url> --target <target url> `
        --types Patient,Observation,MedicationRequest --sample 200 --compare-versions --report report.json

The validator only sends GET requests. Its report holds resource ids and element paths, never values.

## What was verified

* `scripts/test_migrate.py`: 16 of 16, against a stand-in written from Microsoft's documentation. The script
  has **not** been run against Azure API for FHIR or the FHIR service.
* Validator self-test: 14 of 14 on the .NET 10 SDK.
* Validator against two HAPI FHIR servers in Docker: see the article for the results. HAPI is not Azure;
  the run proves the tool against real FHIR servers, not against either Azure service.

## Limits

* A sample is not proof. Equal counts and a clean sample of the newest resources do not show that every
  resource arrived intact. Raise `--sample`, and compare whole exports where the risk warrants it.
* Hard deletes on the source are not exported. Track them and apply them to the target yourself.
* The script does not copy server settings, custom search parameters, or role assignments.
