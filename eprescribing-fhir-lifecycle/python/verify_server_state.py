"""An independent look at what the C# run left on the FHIR server, using nothing but HTTP.

    python verify_server_state.py http://127.0.0.1:8081/fhir ids.json [results.json]

The C# self-test asserts through its own store class. This script reads the same prescriptions with plain
searches, so a mistake in the C# mapping cannot hide itself. It then runs the claim race again from Python.
All data is synthetic.
"""
import concurrent.futures
import json
import sys
import urllib.error
import urllib.request

base, ids = sys.argv[1].rstrip("/"), json.load(open(sys.argv[2], encoding="utf-8"))
passed = failed = 0
observed: dict[str, object] = {}


def call(method: str, path: str, body: dict | None = None, headers: dict | None = None):
    request = urllib.request.Request(
        f"{base}/{path}" if path else base, method=method, data=json.dumps(body).encode() if body is not None else None,
        headers={"Accept": "application/fhir+json", "Content-Type": "application/fhir+json", "Cache-Control": "no-cache", **(headers or {})},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, json.loads(response.read().decode() or "{}")
    except urllib.error.HTTPError as error:
        text = error.read().decode()
        return error.code, json.loads(text) if text.startswith("{") else {}


def check(name: str, condition: bool, detail: object = "") -> None:
    global passed, failed
    passed += bool(condition)
    failed += not condition
    print(f"{'ok  ' if condition else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not condition else ""))


def resources(query: str) -> list[dict]:
    return [entry["resource"] for entry in call("GET", query)[1].get("entry", [])]


def picture(request_id: str) -> dict:
    request = call("GET", f"MedicationRequest/{request_id}")[1]
    task = resources(f"Task?focus=MedicationRequest/{request_id}")[0]
    dispenses = resources(f"MedicationDispense?prescription=MedicationRequest/{request_id}&_sort=whenhandedover")
    history = call("GET", f"Task/{task['id']}/_history?_count=50")[1]
    return {
        "request": request["status"], "task": task["status"], "owner": task.get("owner", {}).get("reference"),
        "dispensed_by": [d["performer"][0]["actor"]["reference"] for d in dispenses],
        "dispense_status": sorted({d["status"] for d in dispenses}),
        "task_versions": len(history.get("entry", [])),
        "task_trail": [e["resource"]["status"] for e in reversed(history.get("entry", []))],
        "reason": request.get("statusReason", {}).get("text"),
    }


status, capability = call("GET", "metadata")
observed["server"] = {"software": capability.get("software", {}), "fhirVersion": capability.get("fhirVersion")}

two = picture(ids["two_supplies"])
observed["two_supplies"] = two
check("two supplies: MedicationRequest completed, Task completed", (two["request"], two["task"]) == ("completed", "completed"), two)
check("two supplies: one dispense by each pharmacy, in order", two["dispensed_by"] == ["Organization/pharmacy-a", "Organization/pharmacy-b"], two["dispensed_by"])
check("two supplies: the Task history shows every transition", two["task_trail"] == ["requested", "accepted", "requested", "accepted", "completed"], two["task_trail"])

race = picture(ids["claim_race"])
observed["claim_race"] = race
check("claim race: the Task is accepted and has exactly one owner", race["task"] == "accepted" and race["owner"] in ("Organization/pharmacy-a", "Organization/pharmacy-b"), race)
check("claim race: claim, release, claim is three changes after creation", race["task_trail"] == ["requested", "accepted", "requested", "accepted"], race["task_trail"])

cancelled = picture(ids["cancel_before_dispense"])
observed["cancel_before_dispense"] = cancelled
check("cancel: MedicationRequest cancelled with its reason, Task cancelled, nothing dispensed",
      (cancelled["request"], cancelled["task"], cancelled["dispensed_by"], cancelled["reason"]) == ("cancelled", "cancelled", [], "Prescribed in error"), cancelled)

incoherent = []
outcomes = {"cancelled": 0, "completed": 0}
for request_id in ids["cancel_dispense_races"]:
    p = picture(request_id)
    ok = (p["request"] == "cancelled" and not p["dispensed_by"]) or (p["request"] == "completed" and len(p["dispensed_by"]) == 1)
    outcomes[p["request"]] = outcomes.get(p["request"], 0) + 1
    if not ok:
        incoherent.append((request_id, p))
observed["cancel_dispense_races"] = outcomes
check("races: all 20 prescriptions are cancelled with no dispense or completed with exactly one", not incoherent, incoherent[:2])

expired = picture(ids["expired"])
observed["expired"] = expired
check("expired: MedicationRequest stopped, Task cancelled, nothing dispensed", (expired["request"], expired["task"], expired["dispensed_by"]) == ("stopped", "cancelled", []), expired)

# The claim race again, from a second implementation: two version-aware updates of one Task.
task = resources(f"Task?focus=MedicationRequest/{ids['expired']}")[0]
fresh_task = {k: v for k, v in task.items() if k not in ("id", "meta", "owner")} | {"status": "requested"}
status, created = call("POST", "Task", fresh_task)
task_id, version = created["id"], created["meta"]["versionId"]


def claim(pharmacy: str) -> int:
    body = {**created, "status": "accepted", "owner": {"reference": pharmacy}}
    return call("PUT", f"Task/{task_id}", body, {"If-Match": f'W/"{version}"'})[0]


with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
    statuses = sorted(pool.map(claim, ["Organization/pharmacy-a", "Organization/pharmacy-b"]))
observed["python_claim_race"] = statuses
check("python: two version-aware claims of one Task, one succeeds and one is refused", statuses[0] == 200 and statuses[1] in (409, 412), statuses)

if len(sys.argv) > 3:
    with open(sys.argv[3], "w", encoding="utf-8") as handle:
        json.dump(observed, handle, indent=2)
        handle.write("\n")
print(f"\n{passed} of {passed + failed} checks passed")
sys.exit(1 if failed else 0)
