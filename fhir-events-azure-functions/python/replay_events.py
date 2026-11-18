"""Replays an awkward sequence of FHIR change events against the running Function App and checks the result.

For every step it first changes a real resource on the FHIR server, then delivers events in the Azure Health
Data Services schema to the Function: duplicated, out of order, late, and for resources that are already gone.
The events are built here, not produced by Event Grid.

    python replay_events.py --report report.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid

import requests

FHIR = os.environ.get("FHIR_URL", "http://localhost:8090/fhir").rstrip("/")
FUNC = os.environ.get("FUNC_URL", "http://localhost:7071").rstrip("/")
KEY = os.environ.get("FUNC_KEY", "")
EVENTGRID_KEY = os.environ.get("EVENTGRID_KEY", "")
RUN = time.strftime("%H%M%S")
results: list[dict] = []
session = requests.Session()


def check(name: str, passed: bool, detail: object = "") -> None:
    results.append({"name": name, "passed": bool(passed), "detail": detail})
    print(f"{'PASS' if passed else 'FAIL'}  {name}" + (f"  [{detail}]" if not passed else ""))


def put_observation(resource_id: str, systolic: int, diastolic: int, status: str = "final") -> int:
    body = {"resourceType": "Observation", "id": resource_id, "status": status,
            "code": {"coding": [{"system": "http://loinc.org", "code": "85354-9"}]},
            "subject": {"reference": "Patient/p1"}, "effectiveDateTime": "2026-08-03T09:42:00Z",
            "component": [
                {"code": {"coding": [{"system": "http://loinc.org", "code": "8480-6"}]},
                 "valueQuantity": {"value": systolic, "unit": "mmHg", "system": "http://unitsofmeasure.org", "code": "mm[Hg]"}},
                {"code": {"coding": [{"system": "http://loinc.org", "code": "8462-4"}]},
                 "valueQuantity": {"value": diastolic, "unit": "mmHg", "system": "http://unitsofmeasure.org", "code": "mm[Hg]"}}]}
    response = session.put(f"{FHIR}/Observation/{resource_id}", json=body, timeout=30,
                           headers={"Content-Type": "application/fhir+json"})
    response.raise_for_status()
    return int(response.json()["meta"]["versionId"])


def delete_observation(resource_id: str) -> int:
    session.delete(f"{FHIR}/Observation/{resource_id}", timeout=30).raise_for_status()
    history = session.get(f"{FHIR}/Observation/{resource_id}/_history", params={"_count": "1"}, timeout=30,
                          headers={"Cache-Control": "no-cache"}).json()
    return int(history["entry"][0]["request"]["url"].rsplit("/", 1)[-1]) if "request" in history["entry"][0] \
        else int(history["entry"][0]["resource"]["meta"]["versionId"])


def event(kind: str, resource_id: str, version: int, resource_type: str = "Observation") -> dict:
    return {"id": str(uuid.uuid4()),
            "topic": "/subscriptions/0000/resourceGroups/rg/providers/Microsoft.HealthcareApis/workspaces/ws",
            "subject": f"fhir.example/{resource_type}/{resource_id}",
            "eventType": f"Microsoft.HealthcareApis.FhirResource{kind}",
            "eventTime": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "data": {"resourceType": resource_type, "resourceFhirAccount": "fhir.example",
                     "resourceFhirId": resource_id, "resourceVersionId": version},
            "dataVersion": str(version), "metadataVersion": "1"}


def deliver(*events: dict) -> dict:
    response = session.post(f"{FUNC}/api/events", params={"code": KEY}, json=list(events), timeout=60)
    response.raise_for_status()
    return response.json()


def outcome(*events: dict) -> list[str]:
    return [r["outcome"] for r in deliver(*events)["results"]]


def projection(resource_id: str) -> dict | None:
    response = session.get(f"{FUNC}/api/projection/{resource_id}", params={"code": KEY}, timeout=30)
    return None if response.status_code == 404 else response.json()


def wait_until_ready(seconds: int) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            if session.get(f"{FUNC}/api/projection/none", params={"code": KEY}, timeout=5).status_code == 404:
                return
        except requests.RequestException:
            pass
        time.sleep(3)
    raise SystemExit(f"The Function App did not answer at {FUNC} within {seconds} s")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report")
    parser.add_argument("--wait", type=int, default=240)
    args = parser.parse_args()
    wait_until_ready(args.wait)
    bp1, bp2, bp3, bp4 = (f"evt-{RUN}-bp{n}" for n in (1, 2, 3, 4))

    v1 = put_observation(bp1, 142, 88)
    created = event("Created", bp1, v1)
    check("a create event is applied", outcome(created) == ["Applied"])
    row = projection(bp1)
    check("the projection holds version 1 with 142/88", row and (row["version"], row["systolic"], row["diastolic"]) == (v1, 142, 88), row)
    check("the same event delivered again changes nothing", outcome(created) == ["SkippedNotNewer"] and projection(bp1) == row)

    v2 = put_observation(bp1, 140, 88)
    v3 = put_observation(bp1, 138, 86)
    check("the later of two updates, delivered first, is applied", outcome(event("Updated", bp1, v3)) == ["Applied"])
    check("the earlier update, arriving late, is skipped", outcome(event("Updated", bp1, v2)) == ["SkippedNotNewer"])
    row = projection(bp1)
    check("the projection holds version 3 with 138/86", row and (row["version"], row["systolic"]) == (v3, 138), row)

    v4 = put_observation(bp1, 138, 86, status="entered-in-error")
    correction = event("Updated", bp1, v4)
    check("a correction to entered-in-error is applied", outcome(correction) == ["Applied"])
    row = projection(bp1)
    check("the row is kept as retracted, with its values removed",
          row and row["retracted"] and not row["deleted"] and row["systolic"] is None and row["version"] == v4, row)

    v5 = delete_observation(bp1)
    check("a delete event writes a tombstone", outcome(event("Deleted", bp1, v5)) == ["Tombstoned"])
    check("the correction, delivered again after the delete, is skipped", outcome(correction) == ["SkippedNotNewer"])
    row = projection(bp1)
    check("the projection records the reading as deleted", row and row["deleted"] and row["version"] == v5, row)

    put_observation(bp2, 128, 82)
    latest = put_observation(bp2, 126, 80)
    check("an old event for a resource that has moved on is applied", outcome(event("Created", bp2, 1)) == ["Applied"])
    row = projection(bp2)
    check("what was projected is the current state, not the version the event named",
          row and (row["version"], row["systolic"]) == (latest, 126), row)
    check("the event for that later version is then a no-op", outcome(event("Updated", bp2, latest)) == ["SkippedNotNewer"])

    put_observation(bp3, 150, 94)
    gone_version = delete_observation(bp3)
    check("a create event for a resource already deleted is skipped as gone", outcome(event("Created", bp3, 1)) == ["SkippedGone"])
    check("nothing was projected for it", projection(bp3) is None)
    check("its delete event then writes the tombstone", outcome(event("Deleted", bp3, gone_version)) == ["Tombstoned"])

    malformed = event("Updated", bp2, latest)
    del malformed["data"]["resourceVersionId"]
    mixed = deliver(event("Created", "p1", 1, resource_type="Patient"), malformed, event("Updated", bp2, latest))
    check("in one delivery, another resource type is ignored, a malformed event is dropped, a duplicate is skipped",
          [r["outcome"] for r in mixed["results"]] == ["Ignored", "SkippedNotNewer"] and len(mixed["rejected"]) == 1, mixed)

    handshake = session.post(f"{FUNC}/api/events", params={"code": KEY}, timeout=30, json=[
        {"id": "v", "eventType": "Microsoft.EventGrid.SubscriptionValidationEvent", "data": {"validationCode": "512d38b6"}}])
    check("the Event Grid validation handshake is answered", handshake.json() == {"validationResponse": "512d38b6"}, handshake.text[:100])
    options = session.options(f"{FUNC}/api/events", params={"code": KEY}, headers={"WebHook-Request-Origin": "eventgrid.azure.net"}, timeout=30)
    check("the CloudEvents validation handshake is answered", options.headers.get("WebHook-Allowed-Origin") == "eventgrid.azure.net", dict(options.headers))
    check("a delivery without a key is refused", session.post(f"{FUNC}/api/events", json=[created], timeout=30).status_code == 401)

    # The Event Grid trigger itself, invoked the way Event Grid calls a Function.
    v = put_observation(bp4, 131, 84)
    trigger = session.post(f"{FUNC}/runtime/webhooks/eventgrid", timeout=60,
                           params={"functionName": "ProjectFromEventGrid", "code": EVENTGRID_KEY},
                           headers={"aeg-event-type": "Notification"}, json=[event("Created", bp4, v)])
    row = None
    for _ in range(10):
        row = projection(bp4)
        if row:
            break
        time.sleep(1)
    check("the Event Grid trigger accepts a delivery and the projection follows",
          trigger.status_code in (200, 202) and row and row["systolic"] == 131, {"status": trigger.status_code, "row": row})

    for leftover in (bp2, bp4):
        session.delete(f"{FHIR}/Observation/{leftover}", timeout=30)

    failed = [r for r in results if not r["passed"]]
    print(f"\n{len(results) - len(failed)} of {len(results)} checks passed")
    if args.report:
        with open(args.report, "w", encoding="utf-8") as handle:
            json.dump({"ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "fhir": FHIR, "function": FUNC,
                       "passed": len(results) - len(failed), "total": len(results), "results": results}, handle, indent=2, default=str)
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:  # write a report even when the run cannot finish
        check("the run completed", False, f"{type(error).__name__}: {error}")
        if "--report" in sys.argv:
            with open(sys.argv[sys.argv.index("--report") + 1], "w", encoding="utf-8") as handle:
                json.dump({"ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "passed": sum(r["passed"] for r in results),
                           "total": len(results), "results": results}, handle, indent=2, default=str)
        sys.exit(1)
