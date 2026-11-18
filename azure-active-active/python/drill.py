"""A failover drill against two running instances of the API, one per "region".

    python drill.py http://127.0.0.1:5081 http://127.0.0.1:5082

It does what a client behind a global load balancer experiences: book through one region, lose that region,
retry the same request through the other. Each instance keeps its own memory, so this shows the request
contract (idempotency key, readiness, region headers) and not replication.
"""
import json
import sys
import urllib.error
import urllib.request

north, west = sys.argv[1], sys.argv[2]
passed = failed = 0


def call(base: str, path: str, method: str = "GET", body: dict | None = None, key: str | None = None):
    headers = {"content-type": "application/json"}
    if key:
        headers["Idempotency-Key"] = key
    request = urllib.request.Request(base + path, method=method, headers=headers, data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, dict(response.headers), response.read().decode()
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers), error.read().decode()


def check(name: str, condition: bool) -> None:
    global passed, failed
    passed += condition
    failed += not condition
    print(f"{'ok  ' if condition else 'FAIL'}  {name}")


booking = {"slotId": "slot-2026-10-26-0900", "patientReference": "Patient/synthetic-0042"}
status, headers, _ = call(north, "/ready")
check("north reports ready and names itself", status == 200 and headers.get("x-region") == "north")
status, headers, body = call(north, "/bookings", "POST", booking, key="drill-1")
check("a booking through north is created and decided in north", status == 201 and headers.get("x-decided-in") == "north")
status2, _, body2 = call(north, "/bookings", "POST", booking, key="drill-1")
check("the same request retried gets the same answer, not a conflict", status2 == 201 and body2 == body)
status, _, _ = call(north, "/bookings", "POST", {**booking, "patientReference": "Patient/synthetic-0077"}, key="drill-2")
check("a different patient asking for the same slot is refused", status == 409)
status, _, _ = call(north, "/bookings", "POST", booking)
check("a booking with no idempotency key is refused", status == 400)

status, _, _ = call(north, "/admin/drain", "POST")
status, headers, body = call(north, "/ready")
check("after a drain, north fails its readiness probe", status == 503 and "draining" in body)
status, _, _ = call(north, "/healthz")
check("and is still alive: liveness and readiness are different questions", status == 200)
status, headers, _ = call(west, "/ready")
check("west is ready to take the traffic", status == 200 and headers.get("x-region") == "west")
status, headers, _ = call(west, "/bookings", "POST", {"slotId": "slot-2026-10-26-0930", "patientReference": "Patient/synthetic-0042"}, key="drill-3")
check("a new booking is served by west", status == 201 and headers.get("x-decided-in") == "west")

print(f"\n{passed} of {passed + failed} checks passed")
sys.exit(1 if failed else 0)
