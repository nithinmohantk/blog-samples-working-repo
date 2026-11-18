"""
bp_mapping.py
Maps an openEHR blood pressure OBSERVATION (archetype blood_pressure.v2, canonical JSON) to a
FHIR R4 Observation, and reports what the FHIR resource could not carry.
A hand-written mapping for one archetype, to show the shape of the problem. Real programmes use a
mapping language and engine; the principle of reporting loss applies to both.
"""
from dataclasses import dataclass, field

BP_ARCHETYPE = "openEHR-EHR-OBSERVATION.blood_pressure.v2"
LOINC, UCUM, SNOMED = "http://loinc.org", "http://unitsofmeasure.org", "http://snomed.info/sct"
COMPOSITION_ID_SYSTEM = "urn:openehr:composition-uid"

# archetype node -> (LOINC code, display)
COMPONENTS = {"at0004": ("8480-6", "Systolic blood pressure"), "at0005": ("8462-4", "Diastolic blood pressure")}
# archetype-local code for Location of measurement -> SNOMED CT body site. Deliberately incomplete.
BODY_SITES = {"at0025": ("368209003", "Right upper arm structure")}


@dataclass
class MappingReport:
    mapped: list[str] = field(default_factory=list)
    not_carried: list[str] = field(default_factory=list)      # present in openEHR, absent from the FHIR output


def _items(tree: dict | None) -> dict[str, dict]:
    return {item["archetype_node_id"]: item for item in (tree or {}).get("items", [])}


def blood_pressure_to_fhir(composition: dict, patient_id: str) -> tuple[list[dict], MappingReport]:
    """One FHIR Observation per openEHR event. patient_id comes from your EHR-to-Patient index, not from here."""
    report, out = MappingReport(), []
    uid = composition["uid"]["value"]
    for entry in composition.get("content", []):
        if entry.get("archetype_node_id") != BP_ARCHETYPE:
            report.not_carried.append(f"entry {entry.get('archetype_node_id')}: no mapping defined")
            continue
        protocol = _items(entry.get("protocol"))
        for event in entry["data"]["events"]:
            values, components = _items(event.get("data")), []
            for node, (code, display) in COMPONENTS.items():
                if node not in values:
                    continue
                quantity = values[node]["value"]
                if quantity["units"] != "mm[Hg]":
                    raise ValueError(f"{node}: expected mm[Hg], got {quantity['units']}")
                components.append({
                    "code": {"coding": [{"system": LOINC, "code": code, "display": display}]},
                    "valueQuantity": {"value": quantity["magnitude"], "unit": "mmHg", "system": UCUM, "code": "mm[Hg]"},
                })
                report.mapped.append(f"{values[node]['name']['value']} -> component {code}")
            if not components:
                report.not_carried.append("event without systolic or diastolic: skipped")
                continue
            observation = {
                "resourceType": "Observation",
                "status": "final",
                "identifier": [{"system": COMPOSITION_ID_SYSTEM, "value": uid}],      # the way back to the source
                "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/observation-category",
                                          "code": "vital-signs"}]}],
                "code": {"coding": [{"system": LOINC, "code": "85354-9", "display": "Blood pressure panel"}]},
                "subject": {"reference": f"Patient/{patient_id}"},
                "effectiveDateTime": event["time"]["value"],
                "component": components,
            }
            site = protocol.get("at0014")
            if site:
                local = site["value"]["defining_code"]["code_string"]
                if local in BODY_SITES:
                    code, display = BODY_SITES[local]
                    observation["bodySite"] = {"coding": [{"system": SNOMED, "code": code, "display": display}]}
                    report.mapped.append(f"Location of measurement -> bodySite {code}")
                else:
                    report.not_carried.append(f"Location of measurement '{site['value']['value']}': no SNOMED mapping")
            for node, item in values.items():
                if node not in COMPONENTS:
                    report.not_carried.append(f"data/{item['name']['value']}")
            for item in _items(event.get("state")).values():
                report.not_carried.append(f"state/{item['name']['value']} = {item['value'].get('value')}")
            for node, item in protocol.items():
                if node != "at0014":
                    report.not_carried.append(f"protocol/{item['name']['value']} = {item['value'].get('value')}")
            out.append(observation)
    return out, report


def fhir_to_blood_pressure(observation: dict) -> dict:
    """The reverse direction, to show what a round trip can and cannot restore."""
    by_loinc = {c["code"]["coding"][0]["code"]: c["valueQuantity"] for c in observation.get("component", [])}
    items = [
        {"_type": "ELEMENT", "archetype_node_id": node, "name": {"value": display.split()[0]},
         "value": {"_type": "DV_QUANTITY", "magnitude": by_loinc[code]["value"], "units": by_loinc[code]["code"]}}
        for node, (code, display) in COMPONENTS.items() if code in by_loinc
    ]
    time = {"_type": "DV_DATE_TIME", "value": observation["effectiveDateTime"]}
    return {
        "_type": "OBSERVATION", "archetype_node_id": BP_ARCHETYPE, "name": {"_type": "DV_TEXT", "value": "Blood pressure"},
        "data": {"_type": "HISTORY", "archetype_node_id": "at0001", "origin": time,
                 "events": [{"_type": "POINT_EVENT", "archetype_node_id": "at0006", "time": time,
                             "data": {"_type": "ITEM_TREE", "archetype_node_id": "at0003", "items": items}}]},
    }
