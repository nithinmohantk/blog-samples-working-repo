"""Synthetic record for one made-up patient, as a FHIR R4 transaction. No real people or organisations."""
import json
from pathlib import Path

P = "Patient/ehds-p1"


def org(id_, name):
    return {"resourceType": "Organization", "id": id_, "name": name}


def prac(id_, family, given):
    return {"resourceType": "Practitioner", "id": id_, "name": [{"family": family, "given": [given]}]}


def obs(id_, category, loinc, display, value, unit, performer, when):
    return {"resourceType": "Observation", "id": id_, "status": "final",
            "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/observation-category",
                                      "code": category}]}],
            "code": {"coding": [{"system": "http://loinc.org", "code": loinc, "display": display}]},
            "subject": {"reference": P}, "effectiveDateTime": when,
            "valueQuantity": {"value": value, "unit": unit},
            "performer": [{"reference": performer}]}


RESOURCES = [
    {"resourceType": "Patient", "id": "ehds-p1", "name": [{"family": "Sample", "given": ["Alex"]}],
     "birthDate": "1971-05-04"},
    org("hospital-a", "Hospital A"), org("gp-b", "GP Practice B"), org("pharmacy-c", "Pharmacy C"),
    org("lab-d", "Laboratory D"),
    {"resourceType": "Device", "id": "ehr-system", "deviceName": [{"name": "Example EHR 1.0", "type": "user-friendly-name"}],
     "owner": {"reference": "Organization/hospital-a"}},   # the observer in every AuditEvent; HAPI checks it exists
    prac("dr-hosp-a", "Hospital-A", "Dr"), prac("dr-gp-b", "GP-B", "Dr"), prac("dr-ed-a", "Emergency-A", "Dr"),
    {"resourceType": "Composition", "id": "summary-1", "status": "final",
     "type": {"coding": [{"system": "http://loinc.org", "code": "60591-5", "display": "Patient summary Document"}]},
     "subject": {"reference": P}, "date": "2024-03-01", "author": [{"reference": "Organization/gp-b"}],
     "title": "Patient summary"},
    {"resourceType": "MedicationRequest", "id": "rx-1", "status": "active", "intent": "order",
     "medicationCodeableConcept": {"text": "Metformin 500 mg tablets"}, "subject": {"reference": P},
     "authoredOn": "2024-03-01", "requester": {"reference": "Organization/gp-b"}},
    {"resourceType": "MedicationDispense", "id": "dispense-1", "status": "completed",
     "medicationCodeableConcept": {"text": "Metformin 500 mg tablets"}, "subject": {"reference": P},
     "whenHandedOver": "2024-03-02", "performer": [{"actor": {"reference": "Organization/pharmacy-c"}}]},
    obs("hba1c-1", "laboratory", "4548-4", "Hemoglobin A1c", 7.4, "%", "Organization/lab-d", "2024-02-20"),
    obs("creat-1", "laboratory", "2160-0", "Creatinine", 88, "umol/L", "Organization/lab-d", "2024-02-20"),
    obs("bp-1", "vital-signs", "8480-6", "Systolic blood pressure", 138, "mm[Hg]", "Organization/gp-b", "2024-03-01"),
    {"resourceType": "DiagnosticReport", "id": "lab-report-1", "status": "final",
     "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/v2-0074", "code": "LAB"}]}],
     "code": {"text": "Renal and glycaemic panel"}, "subject": {"reference": P}, "issued": "2024-02-21T09:00:00Z",
     "performer": [{"reference": "Organization/lab-d"}], "result": [{"reference": "Observation/hba1c-1"},
                                                                  {"reference": "Observation/creat-1"}]},
    {"resourceType": "DiagnosticReport", "id": "xray-report-1", "status": "final",
     "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/v2-0074", "code": "RAD"}]}],
     "code": {"text": "Chest X-ray report"}, "subject": {"reference": P}, "issued": "2024-01-10T15:00:00Z",
     "performer": [{"reference": "Organization/hospital-a"}]},
    {"resourceType": "DocumentReference", "id": "discharge-1", "status": "current",
     "type": {"coding": [{"system": "http://loinc.org", "code": "18842-5", "display": "Discharge summary"}]},
     "subject": {"reference": P}, "date": "2024-01-12T10:00:00Z", "custodian": {"reference": "Organization/hospital-a"},
     "content": [{"attachment": {"contentType": "text/plain", "data": "U3ludGhldGljIGRpc2NoYXJnZSBzdW1tYXJ5"}}]},
]


def bundle() -> dict:
    return {"resourceType": "Bundle", "type": "transaction",
            "entry": [{"resource": r, "request": {"method": "PUT", "url": f"{r['resourceType']}/{r['id']}"}}
                      for r in RESOURCES]}


if __name__ == "__main__":
    out = Path(__file__).with_name("seed-bundle.json")
    out.write_text(json.dumps(bundle(), indent=1))
    print(f"wrote {out.name}: {len(RESOURCES)} resources")
