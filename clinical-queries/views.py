"""views.py - ViewDefinitions used in the article. Each one becomes a table."""
LOINC_CODE = "code.coding.where(system = 'http://loinc.org').code.first()"


def _component(loinc: str) -> str:
    return f"component.where(code.coding.where(system = 'http://loinc.org' and code = '{loinc}').exists()).valueQuantity.value.first()"


BP_READINGS = {
    "resourceType": "ViewDefinition", "name": "bp_readings", "status": "active", "resource": "Observation",
    "where": [{"path": "code.coding.where(system = 'http://loinc.org' and code = '85354-9').exists()"},
              {"path": "status = 'final'"}],
    "select": [{"column": [
        {"name": "id", "path": "getResourceKey()"},
        {"name": "patient_id", "path": "subject.getReferenceKey(Patient)"},
        {"name": "effective", "path": "effectiveDateTime"},
        {"name": "systolic", "path": _component("8480-6")},
        {"name": "diastolic", "path": _component("8462-4")},
    ]}],
}

LAB_RESULTS = {
    "resourceType": "ViewDefinition", "name": "lab_results", "status": "active", "resource": "Observation",
    "where": [{"path": "category.coding.where(code = 'laboratory').exists()"}, {"path": "status = 'final'"}],
    "select": [{"column": [
        {"name": "id", "path": "getResourceKey()"},
        {"name": "patient_id", "path": "subject.getReferenceKey(Patient)"},
        {"name": "loinc", "path": LOINC_CODE},
        {"name": "effective", "path": "effectiveDateTime"},
        {"name": "value", "path": "valueQuantity.value"},
        {"name": "unit", "path": "valueQuantity.code"},
    ]}],
}

MEDICATION_REQUESTS = {
    "resourceType": "ViewDefinition", "name": "medication_requests", "status": "active", "resource": "MedicationRequest",
    "select": [{"column": [
        {"name": "id", "path": "getResourceKey()"},
        {"name": "patient_id", "path": "subject.getReferenceKey(Patient)"},
        {"name": "status", "path": "status"},
        {"name": "medication_code", "path": "medicationCodeableConcept.coding.code.first()"},
        {"name": "medication", "path": "medicationCodeableConcept.text"},
        {"name": "authored", "path": "authoredOn"},
    ]}],
}

# forEach: one row per component, with the observation's own columns repeated beside it.
OBSERVATION_COMPONENTS = {
    "resourceType": "ViewDefinition", "name": "observation_components", "status": "active", "resource": "Observation",
    "select": [
        {"column": [{"name": "observation_id", "path": "getResourceKey()"}]},
        {"forEach": "component", "column": [
            {"name": "loinc", "path": LOINC_CODE},
            {"name": "value", "path": "valueQuantity.value"},
        ]},
    ],
}

ALL_VIEWS = [BP_READINGS, LAB_RESULTS, MEDICATION_REQUESTS, OBSERVATION_COMPONENTS]
