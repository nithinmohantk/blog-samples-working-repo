"""Synthetic data only: no real patient appears in this file. Run: python test_fhir_rag.py"""
import base64

from fhir_retrieval import HashingEmbedder, PatientIndex, build_context, fhir_search_url, retrieve
from fhir_statements import render_bundle

LOINC, SCT, VS = "http://loinc.org", "http://snomed.info/sct", "http://terminology.hl7.org/CodeSystem/"


def cc(system, code, display):
    return {"coding": [{"system": system, "code": code, "display": display}]}


def obs(oid, pid, date, value, status="final"):
    return {"resourceType": "Observation", "id": oid, "status": status, "subject": {"reference": f"Patient/{pid}"},
            "code": cc(LOINC, "4548-4", "Hemoglobin A1c"), "effectiveDateTime": date,
            "valueQuantity": {"value": value, "unit": "%"}}


NOTE = ("Review of type 2 diabetes. Patient reports good adherence to metformin.\n\n"
        "Foot examination normal. Reports occasional dizziness on standing in the mornings.\n\n"
        "Plan: continue current treatment, repeat HbA1c in three months.")
resources = [
    {"resourceType": "Patient", "id": "p1"},
    obs("o1", "p1", "2025-11-03", 8.1), obs("o2", "p1", "2026-06-02", 7.2),
    obs("o3", "p1", "2026-06-20", 71.0, status="entered-in-error"),            # a keying error, later corrected
    {"resourceType": "Condition", "id": "c1", "subject": {"reference": "Patient/p1"},
     "clinicalStatus": cc(VS + "condition-clinical", "active", "Active"),
     "verificationStatus": cc(VS + "condition-ver-status", "confirmed", "Confirmed"),
     "code": cc(SCT, "44054006", "Type 2 diabetes mellitus"), "onsetDateTime": "2019-04-11"},
    {"resourceType": "Condition", "id": "c2", "subject": {"reference": "Patient/p1"},
     "verificationStatus": cc(VS + "condition-ver-status", "refuted", "Refuted"),
     "code": cc(SCT, "22298006", "Myocardial infarction")},
    {"resourceType": "MedicationRequest", "id": "m1", "status": "active", "intent": "order",
     "subject": {"reference": "Patient/p1"}, "authoredOn": "2024-02-01",
     "medicationCodeableConcept": {"text": "Metformin 500 mg tablets"}, "dosageInstruction": [{"text": "one tablet twice daily"}]},
    {"resourceType": "MedicationRequest", "id": "m2", "status": "stopped", "intent": "order",
     "subject": {"reference": "Patient/p1"}, "authoredOn": "2023-05-10",
     "medicationCodeableConcept": {"text": "Gliclazide 80 mg tablets"}, "dosageInstruction": [{"text": "one tablet daily"}]},
    {"resourceType": "AllergyIntolerance", "id": "a1", "patient": {"reference": "Patient/p1"}, "criticality": "high",
     "code": {"text": "Penicillin"}, "reaction": [{"manifestation": [{"text": "anaphylaxis"}]}]},
    {"resourceType": "DocumentReference", "id": "d1", "status": "current", "subject": {"reference": "Patient/p1"},
     "date": "2026-06-02T10:15:00Z", "type": {"text": "Clinic note"},
     "content": [{"attachment": {"contentType": "text/plain", "data": base64.b64encode(NOTE.encode()).decode()}}]},
    {"resourceType": "Immunization", "id": "i1", "patient": {"reference": "Patient/p1"}},
    # A second patient whose record matches the test questions more closely than patient 1's does.
    {"resourceType": "Patient", "id": "p2"},
    obs("o9", "p2", "2026-07-01", 11.4),
    {"resourceType": "DocumentReference", "id": "d9", "status": "current", "subject": {"reference": "Patient/p2"},
     "date": "2026-07-01T09:00:00Z", "type": {"text": "Clinic note"},
     "content": [{"attachment": {"contentType": "text/plain",
                                 "data": base64.b64encode(b"Dizziness on standing. Dizziness in the mornings. Dizziness.").decode()}}]},
]
report = render_bundle({"resourceType": "Bundle", "entry": [{"resource": r} for r in resources]})
print("excluded   ->", report.excluded)
print("unsupported->", report.unsupported)
assert ("Observation/o3", "status=entered-in-error") in report.excluded
assert ("Condition/c2", "verificationStatus=refuted") in report.excluded
assert report.unsupported == ["Immunization"]
assert all(s.resource and s.patient_id for s in report.statements)               # provenance on everything

index = PatientIndex(HashingEmbedder())
index.add(report.statements)

latest = retrieve(index, "p1", "What is the latest HbA1c?")
print("structured ->", [s.text for s in latest["evidence"]])
assert latest["route"] == "structured" and [s.resource for s in latest["evidence"]] == ["Observation/o2"]
assert "7.2 %" in latest["evidence"][0].text                                    # not 71.0, not patient 2's 11.4

dizzy = retrieve(index, "p1", "Has the patient mentioned dizziness?")
print("semantic   ->", [s.resource for s in dizzy["evidence"]])
assert dizzy["route"] == "semantic" and dizzy["evidence"][0].resource == "DocumentReference/d1"
assert all(s.patient_id == "p1" for s in dizzy["evidence"] + dizzy["pinned"])    # patient 2 never appears

context = build_context(dizzy)
print(context)
assert "Penicillin" in context and "Metformin" in context                        # pinned regardless of the question
assert "Gliclazide" not in context.split("EVIDENCE")[0]                          # a stopped drug is not pinned as current
assert "Myocardial" not in context and "71.0" not in context

assert retrieve(index, "nobody", "latest HbA1c")["evidence"] == []
url = fhir_search_url("https://fhir.example/r4/", "p1", LOINC, "4548-4")
print(url)
assert url == "https://fhir.example/r4/Observation?patient=p1&code=http%3A%2F%2Floinc.org%7C4548-4&_sort=-date&_count=1"
assert index.purge("p1") > 0 and index.statements("p1") == []
print("ALL FHIR RAG TESTS OK")
