# cms-0057f-payer-to-payer

Sample for the dataa.dev article *CMS-0057-F for FHIR Teams: The Payer-to-Payer Five-Year Window and What Bulk Data Can Filter* (20 January 2024).

A previous payer answering a payer-to-payer request under the CMS Interoperability and Prior Authorization final rule: a FHIR Bulk Data 1.0 Group export of the members who opted in, then the five-year date-of-service window applied per resource.

| Path | What it is |
| :--- | :--- |
| `client/bulk_export.py` | Bulk Data 1.0 client: kick-off, polling with Retry-After, NDJSON download. Standard library only |
| `client/service_window.py` | The five-year window: which element is the date of service for each resource type, and what happens without one |
| `data/seed.py` | Writes a synthetic transaction Bundle: four members, three opted in, data from 2016 to 2023 |
| `tools/run_experiments.py` | Loads the data into HAPI FHIR and runs the export five ways |
| `tests/` | 12 unit tests: window boundaries and the client against a scripted Bulk Data server |
| `ci.sh` | Everything the workflow runs |

## Run

```
./ci.sh out        # needs Docker and Python 3.12 with pytest
```

In GitHub Actions this is `.github/workflows/cms-p2p.yml`; results go to the branch `ci-results-cms-p2p`.

## What was verified

GitHub Actions, `hapiproject/hapi:v6.10.1` (HAPI FHIR 6.10.0, FHIR 4.0.1) with `hapi.fhir.bulk_export_enabled=true`, Python 3.12, pytest 7.4.4 (resolved as of 19 January 2024). Request date 19 January 2024; window from 19 January 2019.

| Run | Claims | Encounters, conditions, observations | Note |
| :--- | :--- | :--- | :--- |
| Group export, no filter | 10 | 9 | Opted-in members 1, 2 and 4 only |
| `_since=2019-01-19T00:00:00Z` | 10 | 9 | Same: `_since` compares with `meta.lastUpdated` |
| `_typeFilter=ExplanationOfBenefit?service-date=ge2019-01-19` without a registered parameter | - | - | Kick-off accepted (202); the job then failed and the status URL returned 500, HAPI-0488 |
| `_typeFilter` with a registered `service-date` parameter, plus `date`/`recorded-date` filters | 7 | 5 | Includes a claim dated after the request; drops the undated condition silently |
| Export, then `service_window.py` | 6 | 5 | Old, future-dated and undated items listed, undated one held for review |

## What was not verified

- Authentication: the HAPI server is open. Production endpoints need SMART Backend Services or another payer-to-payer trust framework.
- Provider Access attribution, the Patient Access additions and the Prior Authorization API are described in the article but not built here.
- No US Core or CARIN Blue Button validation of the exported resources. The `service-date` search parameter is modelled on CARIN Blue Button's and is not the IG's own resource.
- All data is synthetic. This is not legal advice on the rule.
