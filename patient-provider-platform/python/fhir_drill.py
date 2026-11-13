"""Two FHIR R4 interactions the design depends on, exercised against a real server.

    python fhir_drill.py http://127.0.0.1:8080/fhir [results.json]

1. Version-aware update: two clients read the same free Slot and both try to mark it busy with If-Match.
   One must win and the other must be refused.
2. Conditional create: the same Appointment is posted three times with If-None-Exist. One must exist.

All data is synthetic. The script also leaves Patient/synthetic-0042 and Slot/slot-drill-2 in place for the
C# gateway check that runs after it.
"""
import concurrent.futures
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

base = sys.argv[1].rstrip("/")
SYSTEM = "https://example.org/platform/appointment-id"
passed = failed = 0
observed: dict[str, object] = {}


def call(method: str, path: str, body: dict | None = None, headers: dict | None = None):
    request = urllib.request.Request(
        f"{base}/{path}", method=method, data=json.dumps(body).encode() if body is not None else None,
        headers={"Accept": "application/fhir+json", "Content-Type": "application/fhir+json", **(headers or {})},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            text = response.read().decode()
            return response.status, dict(response.headers), json.loads(text) if text else {}
    except urllib.error.HTTPError as error:
        text = error.read().decode()
        return error.code, dict(error.headers), json.loads(text) if text.startswith("{") else {}


def check(name: str, condition: bool, detail: object = "") -> None:
    global passed, failed
    passed += bool(condition)
    failed += not condition
    print(f"{'ok  ' if condition else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not condition else ""))


def slot(slot_id: str, status: str) -> dict:
    return {"resourceType": "Slot", "id": slot_id, "schedule": {"reference": "Schedule/sched-drill"}, "status": status,
            "start": "2025-11-17T09:00:00Z", "end": "2025-11-17T09:20:00Z"}


status, _, capability = call("GET", "metadata")
observed["server"] = {"software": capability.get("software", {}), "fhirVersion": capability.get("fhirVersion")}
check("the server is FHIR R4", status == 200 and str(capability.get("fhirVersion", "")).startswith("4.0"), capability.get("fhirVersion"))

call("PUT", "Patient/synthetic-0042", {"resourceType": "Patient", "id": "synthetic-0042", "active": True})
call("PUT", "Practitioner/prac-drill", {"resourceType": "Practitioner", "id": "prac-drill", "active": True})
call("PUT", "Schedule/sched-drill", {"resourceType": "Schedule", "id": "sched-drill", "active": True, "actor": [{"reference": "Practitioner/prac-drill"}]})
for slot_id in ("slot-drill-1", "slot-drill-2"):
    call("PUT", f"Slot/{slot_id}", slot(slot_id, "free"))

# 1. Version-aware update.
status, headers, current = call("GET", "Slot/slot-drill-1")
etag = headers.get("ETag") or headers.get("Etag") or f'W/"{current["meta"]["versionId"]}"'
observed["slot_etag"] = etag
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
    attempts = list(pool.map(lambda _: call("PUT", "Slot/slot-drill-1", slot("slot-drill-1", "busy"), {"If-Match": etag})[0], range(2)))
observed["concurrent_if_match"] = sorted(attempts)
check("two updates with the same If-Match: one succeeds", sorted(attempts)[0] == 200, attempts)
check("and the other is refused with 412 or 409", sorted(attempts)[1] in (409, 412), attempts)
stale = call("PUT", "Slot/slot-drill-1", slot("slot-drill-1", "free"), {"If-Match": etag})[0]
observed["stale_if_match"] = stale
check("a later update with the stale version is refused", stale in (409, 412), stale)
check("the slot is busy", call("GET", "Slot/slot-drill-1")[2].get("status") == "busy")

# 2. Conditional create.
appointment = {
    "resourceType": "Appointment", "status": "booked", "identifier": [{"system": SYSTEM, "value": "appt-drill-000001"}],
    "slot": [{"reference": "Slot/slot-drill-1"}],
    "participant": [{"actor": {"reference": "Patient/synthetic-0042"}, "status": "accepted"}],
}
condition = f"identifier={urllib.parse.quote(SYSTEM, safe='')}|appt-drill-000001"
creates = [call("POST", "Appointment", appointment, {"If-None-Exist": condition})[0] for _ in range(3)]
observed["conditional_create"] = creates
check("the first conditional create returns 201", creates[0] == 201, creates)
check("the second and third create nothing and return 200", creates[1:] == [200, 200], creates)
total = call("GET", f"Appointment?identifier={urllib.parse.quote(SYSTEM, safe='')}|appt-drill-000001&_summary=count")[2].get("total")
observed["appointments_found"] = total
check("one Appointment exists for the identifier", total == 1, total)

if len(sys.argv) > 2:
    with open(sys.argv[2], "w", encoding="utf-8") as handle:
        json.dump(observed, handle, indent=2)
        handle.write("\n")
print(f"\n{passed} of {passed + failed} checks passed")
sys.exit(1 if failed else 0)
