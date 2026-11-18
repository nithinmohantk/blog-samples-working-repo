# RAG over FHIR sample

Companion code for "RAG over FHIR Data on AWS HealthLake and Azure Health Data Services" (dataa.dev, 21 July 2026).

| File | Role |
| --- | --- |
| `fhir_statements.py` | Renders FHIR R4 resources into short clinical statements with provenance; excludes entered-in-error and refuted records; reports unsupported resource types |
| `fhir_retrieval.py` | Patient-partitioned index, structured-first routing, pinned safety facts, context builder, FHIR search URL builder, purge |
| `test_fhir_rag.py` | Synthetic two-patient bundle and assertions for each safety property |

## Run

    python test_fhir_rag.py        # -> ALL FHIR RAG TESTS OK   (Python 3.11+, no dependencies)

## Read before using

* SYNTHETIC DATA ONLY. No real patient data is in this repository. Do not add any.
* This is a reference pattern, not a medical device and not clinically validated. Any use that can
  influence care needs a clinical safety case, a named clinical safety officer and local governance.
* `HashingEmbedder` exists so the tests run offline. Replace it with a real embedding model.
* `PatientIndex` is in-memory. In production the partition is a per-patient filter or index in a
  vector store, enforced by the platform, not by application code alone.
* Nothing here was run against AWS HealthLake or the Azure FHIR service. Only R4 Condition, Observation,
  MedicationRequest, AllergyIntolerance and text/plain DocumentReference are rendered.
* Dates are compared as ISO 8601 strings. Normalise precision and time zones before relying on ordering.
