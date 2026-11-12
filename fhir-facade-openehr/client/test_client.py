"""Test client for the FHIR facade.

Mints short-lived development tokens, calls the facade over HTTP and checks what comes back. It needs the
facade running in Development mode with the same signing secret, and the openEHR repository behind it loaded
with the synthetic patients p1..p5 (see the README).

    python test_client.py --base-url http://localhost:5080/fhir --report report.json

Exit code 0 means every check passed.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import asdict, dataclass

import jwt
import requests

ISSUER = os.environ.get("DEV_ISSUER", "https://dev-issuer.localhost/")
AUDIENCE = os.environ.get("DEV_AUDIENCE", "api://fhir-facade")
BP = {"code": "http://loinc.org|85354-9"}


def mint(secret: str, *, scp: str | None = None, roles: list[str] | None = None, patient: str | None = None,
         audience: str = AUDIENCE, lifetime: int = 300) -> str:
    """A token shaped like the ones Microsoft Entra ID issues: scp for delegated scopes, roles for applications."""
    now = int(time.time())
    claims: dict = {"iss": ISSUER, "aud": audience, "sub": "test-subject", "azp": "test-client",
                    "iat": now, "nbf": now - 5, "exp": now + lifetime}
    if scp is not None:
        claims["scp"] = scp
    if roles is not None:
        claims["roles"] = roles
    if patient is not None:
        claims["fhirUser"] = f"https://facade.example/fhir/Patient/{patient}"
    return jwt.encode(claims, secret, algorithm="HS256")


@dataclass
class Result:
    name: str
    passed: bool
    status: int
    detail: str


class Runner:
    def __init__(self, base_url: str, secret: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.secret = secret
        self.session = requests.Session()
        self.results: list[Result] = []

    def get(self, path: str, token: str | None = None, **params: str) -> requests.Response:
        headers = {"Accept": "application/fhir+json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return self.session.get(f"{self.base_url}/{path}", headers=headers, params=params, timeout=30)

    def check(self, name: str, response: requests.Response, status: int, predicate=lambda body: True, detail="") -> dict:
        try:
            body = response.json() if response.content else {}
        except ValueError:
            body = {}
        passed = response.status_code == status and bool(predicate(body))
        self.results.append(Result(name, passed, response.status_code, detail or ""))
        print(f"{'PASS' if passed else 'FAIL'}  [{response.status_code}] {name}")
        return body

    def wait_until_ready(self, seconds: int) -> None:
        deadline = time.monotonic() + seconds
        while True:
            try:
                if self.get("metadata").status_code == 200:
                    return
            except requests.RequestException:
                pass
            if time.monotonic() > deadline:
                raise SystemExit(f"The facade did not answer at {self.base_url}/metadata within {seconds} s")
            time.sleep(2)


def entries(body: dict) -> list[dict]:
    return [entry["resource"] for entry in body.get("entry", [])]


def systolic(observation: dict) -> float:
    return next(c["valueQuantity"]["value"] for c in observation["component"]
                if c["code"]["coding"][0]["code"] == "8480-6")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default=os.environ.get("FACADE_URL", "http://localhost:5080/fhir"))
    parser.add_argument("--secret", default=os.environ.get("DEV_SIGNING_SECRET"))
    parser.add_argument("--report", help="write the results to this JSON file")
    parser.add_argument("--wait", type=int, default=120, help="seconds to wait for the facade to start")
    args = parser.parse_args()
    if not args.secret:
        raise SystemExit("Set DEV_SIGNING_SECRET or pass --secret (the facade's Auth:DevelopmentSigningSecret).")

    run = Runner(args.base_url, args.secret)
    run.wait_until_ready(args.wait)
    p1 = mint(args.secret, scp="openid patient/Observation.rs", patient="p1")
    p1_entra = mint(args.secret, scp="patient.Observation.read", patient="p1")
    p2 = mint(args.secret, scp="patient/Observation.rs", patient="p2")
    backend = mint(args.secret, roles=["system/Observation.rs"])

    run.check("metadata is public", run.get("metadata"), 200, lambda b: b.get("fhirVersion") == "4.0.1")
    run.check("no token", run.get("Observation", patient="p1", **BP), 401)
    run.check("expired token", run.get("Observation", mint(args.secret, scp="patient/Observation.rs", patient="p1", lifetime=-600), patient="p1", **BP), 401)
    run.check("token signed with another key", run.get("Observation", mint("x" * 48, scp="patient/Observation.rs", patient="p1"), patient="p1", **BP), 401)
    run.check("token for another audience", run.get("Observation", mint(args.secret, scp="patient/Observation.rs", patient="p1", audience="api://something-else"), patient="p1", **BP), 401)

    own = run.check("patient p1 reads own readings, newest first", run.get("Observation", p1, patient="p1", **BP), 200,
                    lambda b: [o["effectiveDateTime"] for o in entries(b)] == ["2026-11-03T09:42:00Z", "2026-08-14T10:00:00Z", "2026-03-02T09:10:00Z"]
                    and [systolic(o) for o in entries(b)] == [142, 146, 150]
                    and all(o["subject"]["reference"] == "Patient/p1" for o in entries(b)))
    run.check("Entra-style scope spelling", run.get("Observation", p1_entra, patient="Patient/p1", **BP), 200, lambda b: len(entries(b)) == 3)
    run.check("patient p1 asks for p2", run.get("Observation", p1, patient="p2", **BP), 403)
    run.check("user/ scope is refused", run.get("Observation", mint(args.secret, scp="user/Observation.rs"), patient="p1", **BP), 403)
    run.check("scope for another resource", run.get("Observation", mint(args.secret, scp="patient/Patient.rs", patient="p1"), patient="p1", **BP), 403)
    run.check("system scope reads p2", run.get("Observation", backend, patient="p2", **BP), 200,
              lambda b: [systolic(o) for o in entries(b)] == [128, 152])
    run.check("patient with no readings", run.get("Observation", backend, patient="p5", **BP), 200, lambda b: entries(b) == [])
    run.check("unsupported parameter", run.get("Observation", backend, patient="p1", category="vital-signs", **BP), 400,
              lambda b: b.get("resourceType") == "OperationOutcome")
    run.check("date without offset", run.get("Observation", backend, patient="p1", date="ge2026-09-01", **BP), 400)

    page1 = run.check("page of two has a next link", run.get("Observation", backend, patient="p1", _count="2", **BP), 200,
                      lambda b: len(entries(b)) == 2 and any(l["relation"] == "next" for l in b["link"]))
    next_url = next((l["url"] for l in page1.get("link", []) if l["relation"] == "next"), "")
    query = next_url.split("?", 1)[1] if "?" in next_url else ""
    response = run.session.get(f"{run.base_url}/Observation?{query}", headers={"Authorization": f"Bearer {backend}"}, timeout=30)
    run.check("next page has the last reading", response, 200,
              lambda b: [systolic(o) for o in entries(b)] == [150] and len(b["link"]) == 1)
    run.check("date range, oldest first",
              run.get("Observation", backend, patient="p1", date=["ge2026-03-01T00:00:00Z", "lt2026-09-01T00:00:00+01:00"], _sort="date", **BP),
              200, lambda b: [systolic(o) for o in entries(b)] == [150, 146])

    first = entries(own)[0] if entries(own) else {"id": "0" * 64}
    run.check("read by id", run.get(f"Observation/{first['id']}", p1), 200, lambda b: b == first)
    run.check("another patient reads that id", run.get(f"Observation/{first['id']}", p2), 404)
    run.check("unknown id", run.get("Observation/" + "0" * 64, backend), 404)

    failed = [r for r in run.results if not r.passed]
    print(f"\n{len(run.results) - len(failed)} of {len(run.results)} checks passed against {run.base_url}")
    if args.report:
        with open(args.report, "w", encoding="utf-8") as handle:
            json.dump({"base_url": run.base_url, "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                       "passed": len(run.results) - len(failed), "total": len(run.results),
                       "results": [asdict(r) for r in run.results]}, handle, indent=2)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
