"""dataset.py - a small synthetic FHIR R4 dataset. No real patient appears here."""
LOINC = "http://loinc.org"
FORMULARY = "urn:example:formulary"
TODAY = "2026-11-12"


def _coding(system: str, code: str, display: str) -> dict:
    return {"coding": [{"system": system, "code": code, "display": display}]}


def bp(oid: str, pid: str, when: str, systolic: int, diastolic: int) -> dict:
    def part(code, display, value):
        return {"code": _coding(LOINC, code, display),
                "valueQuantity": {"value": value, "unit": "mmHg", "system": "http://unitsofmeasure.org", "code": "mm[Hg]"}}
    return {"resourceType": "Observation", "id": oid, "status": "final",
            "category": [_coding("http://terminology.hl7.org/CodeSystem/observation-category", "vital-signs", "Vital Signs")],
            "code": _coding(LOINC, "85354-9", "Blood pressure panel"),
            "subject": {"reference": f"Patient/{pid}"}, "effectiveDateTime": when,
            "component": [part("8480-6", "Systolic blood pressure", systolic),
                          part("8462-4", "Diastolic blood pressure", diastolic)]}


def hba1c(oid: str, pid: str, when: str, value: float) -> dict:
    return {"resourceType": "Observation", "id": oid, "status": "final",
            "category": [_coding("http://terminology.hl7.org/CodeSystem/observation-category", "laboratory", "Laboratory")],
            "code": _coding(LOINC, "4548-4", "Hemoglobin A1c"),
            "subject": {"reference": f"Patient/{pid}"}, "effectiveDateTime": when,
            "valueQuantity": {"value": value, "unit": "%", "system": "http://unitsofmeasure.org", "code": "%"}}


def med(mid: str, pid: str, status: str, code: str, text: str, authored: str) -> dict:
    return {"resourceType": "MedicationRequest", "id": mid, "status": status, "intent": "order",
            "medicationCodeableConcept": {**_coding(FORMULARY, code, text), "text": text},
            "subject": {"reference": f"Patient/{pid}"}, "authoredOn": authored}


RESOURCES: list[dict] = [
    *({"resourceType": "Patient", "id": p} for p in ("p1", "p2", "p3", "p4", "p5")),
    bp("bp-1", "p1", "2026-03-02T09:10:00Z", 150, 94), bp("bp-2", "p1", "2026-08-14T10:00:00Z", 146, 90),
    bp("bp-3", "p1", "2026-11-03T09:42:00Z", 142, 88),
    bp("bp-4", "p2", "2026-05-20T11:30:00Z", 152, 96), bp("bp-5", "p2", "2026-10-28T08:50:00Z", 128, 82),
    bp("bp-6", "p3", "2026-09-09T14:05:00Z", 138, 86),
    bp("bp-7", "p4", "2026-10-30T16:20:00Z", 161, 99),
    hba1c("a1c-1", "p1", "2025-06-10T08:00:00Z", 8.4), hba1c("a1c-2", "p1", "2025-12-15T08:00:00Z", 8.1),
    hba1c("a1c-3", "p1", "2026-06-02T08:00:00Z", 7.9), hba1c("a1c-4", "p1", "2026-10-20T08:00:00Z", 7.7),
    hba1c("a1c-5", "p2", "2026-01-11T08:00:00Z", 8.2), hba1c("a1c-6", "p2", "2026-09-30T08:00:00Z", 6.9),
    hba1c("a1c-7", "p4", "2026-07-07T08:00:00Z", 9.1),
    hba1c("a1c-8", "p5", "2026-08-08T08:00:00Z", 8.0),
    med("mr-1", "p1", "active", "MED-0001", "Metformin 500 mg tablets", "2024-02-01"),
    med("mr-2", "p2", "active", "MED-0001", "Metformin 500 mg tablets", "2025-03-12"),
    med("mr-3", "p4", "stopped", "MED-0001", "Metformin 500 mg tablets", "2023-09-01"),
    med("mr-4", "p4", "active", "MED-0002", "Gliclazide 80 mg tablets", "2026-07-10"),
    med("mr-5", "p5", "active", "MED-0001", "Metformin 500 mg tablets", "2026-08-10"),
]
