# EHDS access logging, restriction and the patient's access report

Sample code for the dataa.dev article *EHDS Provisional Agreement: What EHR Systems Must Build Into the Access Path*.

Implements, on FHIR R4, the parts of the European Health Data Space provisional agreement (Council document 7553/24,
18 March 2024) that sit in an EHR system's access path:

- Article 5(1) priority categories, mapped from FHIR resources (a working assumption until the exchange format exists)
- Annex II point 3.4 logging: one AuditEvent per access with provider, individual, categories, time and origin
- Article 8e restrictions that leave no trace, including a recomputed search total
- Article 7a(3) emergency access, logged with purposeOfEvent ETREAT
- Article 8f access report for the patient, with the individual's name optional, and the three-year minimum

Synthetic data only. Not legal advice.

## What is here

| Path | What it does |
| --- | --- |
| `ehds_access/categories.py` | Article 5(1) categories and the Article 72 four/six-year split. |
| `ehds_access/audit.py` | AuditEvent builder for Annex II 3.4. |
| `ehds_access/restrict.py` | Restriction filter and a searchset Bundle built from what is shown. |
| `ehds_access/gateway.py` | Filter, log what was shown, then return; no log, no data. |
| `ehds_access/report.py` | Article 8f report and the three-year retention check. |
| `ehds_access/fhir.py` | Standard-library FHIR client with retries and jitter. |
| `data/seed.py` | One synthetic patient, four organisations, three clinicians, data in every category. |
| `tools/run_experiments.py` | The scenario against a HAPI FHIR server. |
| `tests/` | 14 unit tests. |

## What was verified

GitHub Actions ([run](https://github.com/nithinmohantk/blog-samples-working-repo/actions/runs/44390722475)), `hapiproject/hapi:v7.0.3` (reports HAPI FHIR Server 7.0.2), Python 3.12.16, pytest 8.1.1 (`--exclude-newer 2024-03-22`).
All 14 unit tests pass. Scenario output:

```text
== 2. The patient restricts test results for everyone except their GP (Article 8e)
Hospital A, Observation: ['bp-1'] total 1   (the server's own total: 3)
Hospital A, DiagnosticReport: ['xray-report-1'] total 1
GP Practice B, Observation: ['hba1c-1', 'creat-1', 'bp-1'] total 3

== 5. Article 8f report for the patient
When (UTC)               Provider                   Who                Data
2024-03-21 02:15:07      Hospital A                 Dr Emergency-A     other, test-results  EMERGENCY ACCESS
2024-03-20 18:40:21      GP Practice B              Dr GP-B            other, test-results
2024-03-20 18:40:14      Hospital A                 Dr Hospital-A      imaging
2024-03-20 18:40:07      Hospital A                 Dr Hospital-A      other
2024-03-20 09:10:14      Hospital A                 Dr Hospital-A      other, test-results
2024-03-20 09:10:07      GP Practice B              Dr GP-B            patient-summary

```

FHIR R4 has no AuditEvent search parameter for `purposeOfEvent`; HAPI rejects `AuditEvent?purpose=` as unknown.
