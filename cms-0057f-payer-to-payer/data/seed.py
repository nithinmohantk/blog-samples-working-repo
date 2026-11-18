"""Writes data/seed-bundle.json: a synthetic payer's data for four members, as one FHIR R4 transaction.

Members 1, 2 and 4 have opted in to payer-to-payer exchange and are in Group/p2p-optin. Member 3 has not
and is not in the Group. Dates of service run from 2016 to 2023, so a request dated 19 January 2024 has
some data inside and some outside the five-year window. Everything is invented.
"""
import json
from pathlib import Path

OUT = Path(__file__).with_name("seed-bundle.json")
entries = []


def put(resource):
    entries.append({"resource": resource,
                    "request": {"method": "PUT", "url": f"{resource['resourceType']}/{resource['id']}"}})


put({"resourceType": "Organization", "id": "payer-old", "name": "Example Previous Health Plan"})
members = {"m1": ("One", True), "m2": ("Two", True), "m3": ("Three", False), "m4": ("Four", True)}
for mid, (given, _) in members.items():
    put({"resourceType": "Patient", "id": mid, "name": [{"family": "Member", "given": [given]}],
         "gender": "unknown", "birthDate": "1980-01-01"})
    put({"resourceType": "Coverage", "id": f"cov-{mid}", "status": "active",
         "beneficiary": {"reference": f"Patient/{mid}"}, "payor": [{"reference": "Organization/payer-old"}],
         "period": {"start": "2015-01-01"}})


def eob(mid, n, start, end):
    put({"resourceType": "ExplanationOfBenefit", "id": f"eob-{mid}-{n}", "status": "active",
         "type": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/claim-type", "code": "professional"}]},
         "use": "claim", "patient": {"reference": f"Patient/{mid}"}, "created": end + "T12:00:00Z",
         "insurer": {"reference": "Organization/payer-old"}, "provider": {"display": "Example Clinic"},
         "outcome": "complete", "billablePeriod": {"start": start, "end": end},
         "insurance": [{"focal": True, "coverage": {"reference": f"Coverage/cov-{mid}"}}]})


def encounter(mid, n, start, end):
    put({"resourceType": "Encounter", "id": f"enc-{mid}-{n}", "status": "finished",
         "class": {"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode", "code": "AMB"},
         "subject": {"reference": f"Patient/{mid}"}, "period": {"start": start, "end": end}})


def condition(mid, n, recorded):
    c = {"resourceType": "Condition", "id": f"cond-{mid}-{n}",
         "clinicalStatus": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-clinical", "code": "active"}]},
         "code": {"text": "Synthetic condition"}, "subject": {"reference": f"Patient/{mid}"}}
    if recorded:
        c["recordedDate"] = recorded
    put(c)


def observation(mid, n, when):
    put({"resourceType": "Observation", "id": f"obs-{mid}-{n}", "status": "final",
         "code": {"text": "Synthetic measurement"}, "subject": {"reference": f"Patient/{mid}"},
         "effectiveDateTime": when, "valueQuantity": {"value": 1, "unit": "1"}})


# Member 1: long history, half of it older than five years.
eob("m1", 1, "2016-03-02", "2016-03-02"); eob("m1", 2, "2018-11-20", "2018-11-21")
eob("m1", 3, "2019-01-18", "2019-01-18"); eob("m1", 4, "2019-01-19", "2019-01-19")
eob("m1", 5, "2022-06-10", "2022-06-10"); eob("m1", 6, "2023-12-01", "2023-12-03")
encounter("m1", 1, "2017-05-05", "2017-05-05"); encounter("m1", 2, "2023-12-01", "2023-12-03")
condition("m1", 1, "2017-05-05"); condition("m1", 2, "2023-12-01")
observation("m1", 1, "2018-02-01"); observation("m1", 2, "2023-12-02")
# Member 2: everything recent.
eob("m2", 1, "2021-04-04", "2021-04-04"); eob("m2", 2, "2023-08-15", "2023-08-15")
encounter("m2", 1, "2023-08-15", "2023-08-15"); observation("m2", 1, "2023-08-15")
# Member 3: has not opted in; must never appear in the export.
eob("m3", 1, "2023-10-10", "2023-10-10"); condition("m3", 1, "2023-10-10")
# Member 4: one condition with no date at all, and a claim dated after the request.
eob("m4", 1, "2020-02-29", "2020-02-29"); condition("m4", 1, None); eob("m4", 2, "2024-02-01", "2024-02-01")

put({"resourceType": "Group", "id": "p2p-optin", "type": "person", "actual": True,
     "name": "Members who opted in to payer-to-payer exchange",
     "member": [{"entity": {"reference": f"Patient/{m}"}} for m, (_, opted) in members.items() if opted]})

OUT.write_text(json.dumps({"resourceType": "Bundle", "type": "transaction", "entry": entries}, indent=1) + "\n")
print(f"{len(entries)} entries written to {OUT.name}")
