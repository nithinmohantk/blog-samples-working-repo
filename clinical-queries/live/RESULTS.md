# Live run: AQL on EHRbase and FHIR search on HAPI FHIR

Run on 12 November 2026 against the local stack in `../docker/docker-compose.yml`.

| Component | Version |
| --- | --- |
| EHRbase | 2.39.0-SNAPSHOT (openEHR SDK 2.36.0, PostgreSQL 16.2) |
| HAPI FHIR | 8.6.0, FHIR R4 (4.0.1), default configuration, no Elasticsearch |

The same synthetic facts as `../dataset.py`: 5 patients, 7 blood pressures, 8 HbA1c results, 5 medication records.
Requests were sent from a browser on the same machine. Authentication was off and both ports were bound to 127.0.0.1.

## How the openEHR data was loaded

1. Templates came from the EHRbase SDK test data
   (`ehrbase/openEHR_SDK`, `test-data/src/main/resources/operationaltemplate/`):
   * `ips.v0.opt`, template id `International Patient Summary`: laboratory results and medication.
   * `EHRN Vital signs.v2.opt`: blood pressure.
2. Both templates remove the Position element (`at0008`) from the blood pressure archetype.
   EHRbase rejected compositions that carried it: `RmObject with type:Element, nodeId:at0008,name:Position; not in template`.
   A copy of the EHRN template was patched to add `at0008` back under `state[at0007]` and uploaded as
   `dataa_vital_signs_position.v1`. All blood pressures were stored with that template.
3. Compositions were built from EHRbase's own example (`GET .../definition/template/adl1.4/{id}/example?format=JSON`)
   and trimmed. The IPS template requires the Medication Summary, Allergies and Problem List sections in every composition.
4. Medication is stored as `openEHR-EHR-ACTION.medication.v1` ("Medication statement"). The IPS template
   rejected instruction state 531 (aborted) for it; the stopped metformin for p4 was stored as 532 (completed).
5. No template I could obtain contains `openEHR-EHR-INSTRUCTION.medication_order.v3`. The templates in the
   EHRbase repository use v0 and v1 of that archetype, and the SDK test templates do not use it at all.
   No medication ORDER data was stored.

## AQL results (EHRbase)

Queries are in `queries.aql`. EHR ids are shown as p1..p5.

| Query | Result |
| --- | --- |
| Q1 latest BP, p1 | `2026-11-03T09:42:00Z, 142, 88` |
| Q2 all readings by EHR, newest first | 7 rows: p4 161; p2 128, 152; p1 142, 146, 150; p3 138 (EHRs ordered by their UUID) |
| Q2 with `GROUP BY e/ehr_id/value` | HTTP 400: `mismatched input 'GROUP' expecting {<EOF>, WHERE, ORDER, LIMIT, '--'}` |
| Q2 `SELECT e/ehr_id/value, MAX(time)` without GROUP BY | 4 rows, one per EHR, each with its latest time (implicit grouping) |
| Q3 HbA1c trend, p1, since 2025-11-12 | `8.1, 7.9, 7.7` |
| Q4 active metformin x HbA1c > 7.5 | 6 rows: p2 8.2 (Jan 2026); p5 8.0; p1 7.7, 7.9, 8.1, 8.4. p4 absent |
| Q4 written as `(COMPOSITION c1 CONTAINS ACTION .. AND COMPOSITION c2 CONTAINS OBSERVATION ..)` | 0 rows, no error. Without the WHERE clause the same FROM returned HTTP 500 |
| Q5 readings taken standing | 2 rows: p1 2026-08-14 146; p2 2026-10-28 128 |
| Article 1 query (p1, systolic >= 140, with position) | 3 rows: 142/88 Sitting; 146/90 Standing; 150/94 Sitting |
| Article 1 query with the alias `AS position` | HTTP 400: `mismatched input 'position' expecting IDENTIFIER`. Alias changed to `patient_position` |

## Queries from the mapping article (EHRbase)

| Query | Result |
| --- | --- |
| Order query (`INSTRUCTION medication_order.v3`, 11 columns) | HTTP 200, 0 rows. Parses; unproven against data |
| Action query as published (`a/instruction_details/instruction_id/id/value`) | HTTP 400: `Not implemented: SELECT: path instruction_details/instruction_id/id/value contains STRUCTURE_INTERMEDIATE attribute instruction_details` |
| Same for `a/instruction_details`, `.../instruction_id`, `.../activity_id` | HTTP 400, same message |
| Action query without that column, since 2020 | 5 rows: p4 2023-09-01 532; p1 2024-02-01 245; p2 2025-03-12 245; p4 2026-07-10 245; p5 2026-08-10 245 |
| `SELECT c/uid/value, a` (whole ACTION) | HTTP 200, full ACTION object. The test actions have no `instruction_details`, so that field was not seen populated |

## FHIR search results (HAPI FHIR)

Requests are in `fhir-search.http`.

| Search | Result |
| --- | --- |
| Q1 | `bp-3` (total 3, `_count=1`) |
| Q2 `component-code-value-quantity ... $ge140` | `bp-1, bp-2, bp-3, bp-4, bp-7`: every reading >= 140, not the latest per patient |
| Q2 `Observation/$lastn?patient=p1&code=...&max=1` | HTTP 200, searchset with ALL 15 observations of all patients. Parameters ignored. `lastn` is listed in the capability statement |
| Q3 | `a1c-2, a1c-3, a1c-4` |
| Q4 two `_has` | `p1, p2, p4, p5` (p2 and p4 are wrong for the intended cohort) |
| Q4 plus `_has:MedicationRequest:subject:status=active` | `p1, p2, p4, p5` (unchanged) |

## Not covered

* Medication ORDER (INSTRUCTION) AQL against real orders: needs a template with `medication_order.v3`.
* Authentication, paging beyond the first page, performance.
* This was an interactive run. There is no script in this folder that repeats it end to end.
