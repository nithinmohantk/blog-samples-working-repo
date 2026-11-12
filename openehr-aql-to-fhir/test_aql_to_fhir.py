"""Synthetic data only. Run: python test_aql_to_fhir.py"""
import json

from aql_to_fhir import medication_orders_to_bundle, set_path

orders = json.load(open("medication_orders.json", encoding="utf-8"))
actions = json.load(open("medication_actions.json", encoding="utf-8"))
bundle, report = medication_orders_to_bundle(orders, actions, {"ehr-aaa": "pat-001"})
by_order = {e["resource"]["identifier"][0]["value"].rsplit(":", 1)[1]: e for e in bundle["entry"]}

print("mapped rows      ->", report.mapped_rows)
print("rejected         ->", report.rejected)
print("unmapped columns ->", report.unmapped_columns)
for note in report.notes:
    print("note             ->", note)

assert bundle["type"] == "transaction" and report.mapped_rows == 4 == len(bundle["entry"])
assert {o: e["resource"]["status"] for o, e in by_order.items()} == {
    "ORD-1001": "active", "ORD-1002": "completed", "ORD-1003": "stopped", "ORD-1004": "unknown"}
assert report.rejected == ["ORD-2001: no FHIR Patient for EHR ehr-zzz", "ORD-1005: missing required medication"]
assert report.unmapped_columns == ["dosage_justification"]

met = by_order["ORD-1001"]["resource"]
assert met["subject"]["reference"] == "Patient/pat-001" and met["intent"] == "order"
assert "coding" not in met["medicationCodeableConcept"]                       # local formulary code not exported
assert met["dosageInstruction"][0]["route"]["coding"][0] == {
    "system": "http://snomed.info/sct", "code": "26643006", "display": "Oral route"}
assert met["dosageInstruction"][0]["timing"]["repeat"]["boundsPeriod"] == {"start": "2026-07-01T00:00:00Z"}
assert met["identifier"][0]["value"] == "11111111-0000-4000-8000-000000000001::synthetic.example:ORD-1001"
assert met["meta"]["source"].endswith("::2")                                  # the exact version it came from
assert by_order["ORD-1001"]["request"] == {
    "method": "PUT",
    "url": "MedicationRequest?identifier=urn%3Aopenehr%3Amedication-order%7C"
           "11111111-0000-4000-8000-000000000001%3A%3Asynthetic.example%3AORD-1001"}
amox = by_order["ORD-1002"]["resource"]
assert amox["dosageInstruction"][0]["timing"]["repeat"]["boundsPeriod"]["end"] == "2026-06-17T00:00:00Z"
assert amox["dosageInstruction"][0]["route"] == {"text": "by mouth"}
assert any("dosage_justification" in n and "ORD-1001" in n for n in report.notes)

# Idempotent: the same input gives byte-identical output.
again, _ = medication_orders_to_bundle(orders, actions, {"ehr-aaa": "pat-001"})
assert json.dumps(again, sort_keys=True) == json.dumps(bundle, sort_keys=True)

probe: dict = {}
set_path(probe, "a[1].b.c", 1)
assert probe == {"a": [{}, {"b": {"c": 1}}]}
json.dump(bundle, open("bundle.python.json", "w", encoding="utf-8"), indent=2, sort_keys=True)
print("ALL AQL-TO-FHIR TESTS OK")
