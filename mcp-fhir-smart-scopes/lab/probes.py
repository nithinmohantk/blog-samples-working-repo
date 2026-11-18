"""Who asks for what, and what should happen. Data, not code."""
from __future__ import annotations

LAB = "http://terminology.hl7.org/CodeSystem/observation-category|laboratory"
VITALS = "http://terminology.hl7.org/CodeSystem/observation-category|vital-signs"

# name: (scopes, patient in context)
PROFILES = {
    "patient-app": ("openid patient/Patient.r patient/Observation.rs", "syn-p1"),
    "labs-only": (f"patient/Observation.rs?category={LAB}", "syn-p1"),
    "meds-view": ("patient/Patient.r patient/MedicationRequest.rs patient/Condition.rs", "syn-p1"),
    "search-only": ("patient/Observation.s", "syn-p1"),
    "self-recorder": (f"patient/Observation.c?category={VITALS} patient/Observation.rs", "syn-p2"),
    "clinician": ("openid fhirUser user/Patient.rs user/Observation.rs user/MedicationRequest.rs user/Condition.rs", None),
    "legacy-v1": ("patient/*.read", "syn-p3"),
    "identity-only": ("openid profile fhirUser", None),
}

HEART_RATE = {"category": "vital-signs", "loinc_code": "8867-4", "display": "Heart rate", "value": 64, "unit": "/min", "effective": "2026-04-01"}

# (profile, tool, arguments, expected): data = an answer with records in it, empty = an answer with none, denied = refused
TYPED = [
    ("patient-app", "get_patient", {}, "data"),
    ("patient-app", "get_patient", {"patient_id": "syn-p2"}, "denied"),
    ("patient-app", "get_patient", {"patient_id": "syn-p1/../syn-p2"}, "denied"),
    ("patient-app", "list_observations", {}, "data"),
    ("patient-app", "list_observations", {"patient_id": "syn-p2"}, "denied"),
    ("patient-app", "get_observation", {"observation_id": "syn-o1-lab1"}, "data"),
    ("patient-app", "get_observation", {"observation_id": "syn-o2-lab1"}, "empty"),
    ("patient-app", "get_observation", {"observation_id": "syn-o2-lab1?_format=json"}, "empty"),
    ("patient-app", "list_medications", {}, "denied"),
    ("patient-app", "search_patients", {"family_name": "Alder"}, "denied"),
    ("patient-app", "record_observation", HEART_RATE, "denied"),
    ("labs-only", "list_observations", {}, "data"),
    ("labs-only", "list_observations", {"category": "laboratory"}, "data"),
    ("labs-only", "list_observations", {"category": "vital-signs"}, "denied"),
    ("labs-only", "get_observation", {"observation_id": "syn-o1-lab1"}, "data"),
    ("labs-only", "get_observation", {"observation_id": "syn-o1-vit1"}, "empty"),
    ("labs-only", "get_patient", {}, "denied"),
    ("meds-view", "list_medications", {}, "data"),
    ("meds-view", "list_conditions", {}, "data"),
    ("meds-view", "list_observations", {}, "denied"),
    ("search-only", "list_observations", {}, "data"),
    ("search-only", "get_observation", {"observation_id": "syn-o1-lab1"}, "denied"),
    ("self-recorder", "record_observation", HEART_RATE, "data"),
    ("self-recorder", "record_observation", {**HEART_RATE, "category": "laboratory"}, "denied"),
    ("self-recorder", "record_observation", {**HEART_RATE, "patient_id": "syn-p1"}, "denied"),
    ("self-recorder", "list_observations", {}, "data"),
    ("clinician", "search_patients", {"family_name": "Alder"}, "data"),
    ("clinician", "list_observations", {"patient_id": "syn-p2"}, "data"),
    ("clinician", "list_observations", {}, "denied"),
    ("clinician", "list_medications", {"patient_id": "syn-p3"}, "data"),
    ("clinician", "record_observation", {**HEART_RATE, "patient_id": "syn-p2"}, "denied"),
    ("legacy-v1", "get_patient", {}, "data"),
    ("legacy-v1", "list_observations", {}, "data"),
    ("legacy-v1", "list_medications", {}, "data"),
    ("legacy-v1", "get_observation", {"observation_id": "syn-o1-lab1"}, "empty"),
    ("legacy-v1", "search_patients", {"family_name": "Alder"}, "denied"),
    ("legacy-v1", "record_observation", HEART_RATE, "denied"),
    ("identity-only", "get_patient", {}, "denied"),
    ("identity-only", "list_observations", {}, "denied"),
]

# name: (scopes, patient) for the generic-tool comparison
GENERIC_PROFILES = {
    "T1": ("patient/Patient.rs patient/Observation.rs", "syn-p1"),
    "T2": (f"patient/Observation.rs?category={LAB}", "syn-p1"),
}

# (profile, path, kind, what it tries): fair = a request the token should be served; hostile = one it should not
GENERIC = [
    ("T1", "Patient/syn-p1", "fair", "own demographics"),
    ("T1", "Observation?code=http://loinc.org|4548-4", "fair", "own HbA1c results"),
    ("T2", "Observation?category=laboratory", "fair", "own laboratory results"),
    ("T1", "Observation/syn-o2-lab1", "hostile", "read another patient's result by id"),
    ("T1", "Observation?patient=syn-p2", "hostile", "search another patient's results"),
    ("T1", "Patient?family=Alder", "hostile", "search patients by name"),
    ("T1", "Patient?_id=syn-p1&_revinclude=MedicationRequest:subject", "hostile", "_revinclude a type with no scope"),
    ("T1", "Patient/syn-p1/$everything", "hostile", "$everything on own record"),
    ("T1", "Patient?_has:Observation:patient:code=4548-4", "hostile", "_has to list patients with a result"),
    ("T1", "Observation?subject.family=Birch", "hostile", "chained search on another patient's name"),
    ("T2", "Observation?_include=Observation:subject", "hostile", "_include a type with no scope"),
    ("T2", "Observation?category=vital-signs", "hostile", "category outside the granted filter"),
    ("T2", "Observation/syn-o1-vit1", "hostile", "read outside the granted filter by id"),
    ("T2", "Observation", "hostile", "search with no category, grant is laboratory only"),
    ("T1", "MedicationRequest?patient=syn-p1", "hostile", "a type with no scope"),
]
