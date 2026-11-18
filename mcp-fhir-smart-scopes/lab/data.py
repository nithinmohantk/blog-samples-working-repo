"""Synthetic records for three invented patients. No real person, no real result."""
from __future__ import annotations

CATEGORY = "http://terminology.hl7.org/CodeSystem/observation-category"
PATIENTS = {"syn-p1": ("Alder", "Test-One", "1971-03-02", "female"), "syn-p2": ("Birch", "Test-Two", "1984-11-19", "male"), "syn-p3": ("Alder", "Test-Three", "1990-06-30", "female")}


def observation(identifier: str, patient: str, category: str, code: str, text: str, value: float, unit: str, when: str) -> dict:
    return {
        "resourceType": "Observation",
        "id": identifier,
        "status": "final",
        "category": [{"coding": [{"system": CATEGORY, "code": category}]}],
        "code": {"coding": [{"system": "http://loinc.org", "code": code}], "text": text},
        "subject": {"reference": f"Patient/{patient}"},
        "effectiveDateTime": when,
        "valueQuantity": {"value": value, "unit": unit},
    }


def resources() -> list[dict]:
    made: list[dict] = []
    for number, (identifier, (family, given, born, gender)) in enumerate(PATIENTS.items(), start=1):
        made.append({"resourceType": "Patient", "id": identifier, "name": [{"family": family, "given": [given]}], "birthDate": born, "gender": gender})
        made.append(observation(f"syn-o{number}-lab1", identifier, "laboratory", "4548-4", "Hemoglobin A1c", 5.0 + number, "%", f"2026-03-0{number}"))
        made.append(observation(f"syn-o{number}-lab2", identifier, "laboratory", "2089-1", "LDL cholesterol", 90.0 + 10 * number, "mg/dL", f"2026-03-1{number}"))
        made.append(observation(f"syn-o{number}-vit1", identifier, "vital-signs", "8867-4", "Heart rate", 60.0 + number, "/min", f"2026-03-2{number}"))
        made.append(observation(f"syn-o{number}-vit2", identifier, "vital-signs", "29463-7", "Body weight", 70.0 + number, "kg", f"2026-03-2{number}"))
        made.append({"resourceType": "MedicationRequest", "id": f"syn-m{number}", "status": "active", "intent": "order", "medicationCodeableConcept": {"text": f"Synthetic medicine {number} 10 mg tablet"}, "subject": {"reference": f"Patient/{identifier}"}, "dosageInstruction": [{"text": "One tablet daily"}]})
        made.append({"resourceType": "Condition", "id": f"syn-c{number}", "clinicalStatus": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-clinical", "code": "active"}]}, "code": {"text": f"Synthetic condition {number}"}, "subject": {"reference": f"Patient/{identifier}"}})
    return made


def bundle() -> dict:
    """A transaction that creates every record under the id given here."""
    return {"resourceType": "Bundle", "type": "transaction", "entry": [{"resource": r, "request": {"method": "PUT", "url": f"{r['resourceType']}/{r['id']}"}} for r in resources()]}
