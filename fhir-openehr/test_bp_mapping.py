"""Synthetic data only. Run: python test_bp_mapping.py"""
import json

from bp_mapping import blood_pressure_to_fhir, fhir_to_blood_pressure

composition = json.load(open("bp_composition.json", encoding="utf-8"))
observations, report = blood_pressure_to_fhir(composition, patient_id="pat-001")
obs = observations[0]
print(json.dumps(obs, indent=2))
print("mapped      ->", report.mapped)
print("not carried ->", report.not_carried)

assert len(observations) == 1 and obs["code"]["coding"][0]["code"] == "85354-9"
values = {c["code"]["coding"][0]["code"]: c["valueQuantity"] for c in obs["component"]}
assert values["8480-6"]["value"] == 142 and values["8462-4"]["value"] == 88
assert all(v["system"] == "http://unitsofmeasure.org" and v["code"] == "mm[Hg]" for v in values.values())
assert obs["effectiveDateTime"] == "2026-08-03T09:42:00+00:00"
assert obs["subject"]["reference"] == "Patient/pat-001"
assert obs["identifier"][0]["value"].startswith("8f2c1a9e")            # provenance back to the composition
assert obs["bodySite"]["coding"][0]["code"] == "368209003"
assert report.not_carried == ["state/Position = Sitting", "protocol/Cuff size = Large Adult"]

# Round trip: the numbers and the time survive, the clinical context does not.
back = fhir_to_blood_pressure(obs)
event = back["data"]["events"][0]
assert [i["value"]["magnitude"] for i in event["data"]["items"]] == [142, 88]
assert event["time"]["value"] == "2026-08-03T09:42:00+00:00"
assert "state" not in event and "protocol" not in back

# A unit the mapping does not expect must stop the pipeline, not pass through.
bad = json.loads(json.dumps(composition))
bad["content"][0]["data"]["events"][0]["data"]["items"][0]["value"]["units"] = "kPa"
try:
    blood_pressure_to_fhir(bad, "pat-001")
    raise AssertionError("kPa was accepted")
except ValueError as exc:
    print("unit check  ->", exc)
print("ALL BP MAPPING TESTS OK")
