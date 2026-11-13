"""An independent look at what the server holds after the messages were applied. Standard library only.

    python verify_server_state.py <output dir>

It reads ids.json written by the C# self-test for the server address and identifier systems, then asks the
server its own questions. It shares no code with the converter.
"""
import json
import pathlib
import sys
import urllib.parse
import urllib.request

out = pathlib.Path(sys.argv[1])
ids = json.loads((out / "ids.json").read_text(encoding="utf-8"))
base, mrn, visit = ids["base"], ids["mrnSystem"], ids["visitSystem"]
passed = failed = 0


def get(path: str) -> dict:
    request = urllib.request.Request(base + path, headers={"Accept": "application/fhir+json", "Cache-Control": "no-cache"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def search(resource: str, **params: str) -> list[dict]:
    query = urllib.parse.urlencode(params | {"_count": "200"})       # urlencode percent-encodes the | in a token
    return [e["resource"] for e in get(f"{resource}?{query}").get("entry", []) if e["resource"]["resourceType"] == resource]


def check(name: str, condition: bool, detail: str = "") -> None:
    global passed, failed
    passed, failed = passed + bool(condition), failed + (not condition)
    print(f"{'ok  ' if condition else 'FAIL'}  {name}{'' if condition or not detail else f'  [{detail}]'}")


def by_number(resource: str, system: str, value: str) -> list[dict]:
    return search(resource, identifier=f"{system}|{value}")


patients = {number: by_number("Patient", mrn, number) for number in ("700001", "700002", "700003", "700009")}
check("each of the four record numbers resolves to exactly one Patient", all(len(found) == 1 for found in patients.values()), str({k: len(v) for k, v in patients.items()}))
totals = {resource: get(f"{resource}?_summary=count")["total"] for resource in ("Patient", "Encounter", "AllergyIntolerance", "Provenance")}
print(f"  totals on the server: {totals}")
check("the server holds 4 patients, 3 encounters, 4 allergies and 12 provenance records", totals == {"Patient": 4, "Encounter": 3, "AllergyIntolerance": 4, "Provenance": 12}, str(totals))

survivor, retired, outpatient, stub = (patients[n][0] for n in ("700001", "700002", "700003", "700009"))
check("exactly one of the two records for the same person is active", survivor.get("active") is True and retired.get("active") is False)
check("the retired records point at the survivor and the survivor points back", all(
    [link["other"]["reference"] for link in record.get("link", []) if link["type"] == "replaced-by"] == [f"Patient/{survivor['id']}"] for record in (retired, stub))
    and sorted(link["other"]["reference"] for link in survivor.get("link", []) if link["type"] == "replaces") == sorted([f"Patient/{retired['id']}", f"Patient/{stub['id']}"]))
check("every identifier on every patient has a system and a value", all(i.get("system") and i.get("value") for p in (survivor, retired, outpatient, stub) for i in p["identifier"]))
check("dates of birth are FHIR dates at the precision received", survivor["birthDate"] == "1985-03-12" and outpatient["birthDate"] == "1980-11")
check("the sparse update removed one address and nothing else", "address" not in outpatient and "address" in survivor and outpatient["name"][0]["family"] == "Walsh")
check("gender is a FHIR code on every patient that has one", all(p.get("gender") in (None, "male", "female", "other", "unknown") for p in (survivor, retired, outpatient, stub)) and outpatient["gender"] == "unknown")

encounters = {number: by_number("Encounter", visit, number) for number in ("V9001", "V9002", "V9003")}
check("each visit number resolves to exactly one Encounter", all(len(found) == 1 for found in encounters.values()))
statuses = {number: found[0]["status"] for number, found in encounters.items()}
check("the stay is finished, the second registration cancelled, the outpatient visit in progress", statuses == {"V9001": "finished", "V9002": "cancelled", "V9003": "in-progress"}, str(statuses))
check("every encounter period carries an offset", all("+" in value or value.endswith("Z") for found in encounters.values() for value in found[0].get("period", {}).values()))

allergies = search("AllergyIntolerance", patient=f"Patient/{survivor['id']}")
labels = sorted(a["code"].get("text", "") for a in allergies)
check("the survivor has three allergies, each once", labels == ["Allergy to peanut", "Allergy to penicillin", "Latex"], str(labels))

history = get(f"Patient/{survivor['id']}/_history?_count=50")
print(f"  Patient/{survivor['id']} has {history.get('total', len(history.get('entry', [])))} versions")
events = search("Provenance", target=f"Patient/{survivor['id']}")
controls = sorted(p["entity"][0]["what"]["identifier"]["value"] for p in events)
check("no provenance exists for the late update or the retried first writer", "MSG00002-LATE" not in controls and "MSG00012" not in controls and len(controls) == 8, str(controls))

(out / "server-state.json").write_text(json.dumps({"totals": totals, "statuses": statuses, "survivor": survivor, "retired": retired, "stub": stub, "outpatient": outpatient}, indent=1) + "\n", encoding="utf-8")
print(f"\n{passed} of {passed + failed} checks passed")
sys.exit(0 if failed == 0 else 1)
