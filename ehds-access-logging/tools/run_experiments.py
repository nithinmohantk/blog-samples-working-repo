"""Runs the access scenarios against a HAPI FHIR server and writes what happened.

    python tools/run_experiments.py http://127.0.0.1:8080/fhir <output dir>
"""
import json
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "data"))
from ehds_access import categories as C  # noqa: E402
from ehds_access.audit import Requester  # noqa: E402
from ehds_access.fhir import FhirClient  # noqa: E402
from ehds_access.gateway import AccessGateway  # noqa: E402
from ehds_access.report import render, rows  # noqa: E402
from ehds_access.restrict import Restriction  # noqa: E402
from seed import P, bundle  # noqa: E402

base, out = sys.argv[1], Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)
HOSPITAL = Requester("Practitioner/dr-hosp-a", "Dr Hospital-A", "Organization/hospital-a", "Hospital A")
GP = Requester("Practitioner/dr-gp-b", "Dr GP-B", "Organization/gp-b", "GP Practice B")
ED = Requester("Practitioner/dr-ed-a", "Dr Emergency-A", "Organization/hospital-a", "Hospital A")
log = []


def say(line=""):
    print(line)
    log.append(line)


def wait_for_server(seconds=300):
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{base}/metadata", timeout=10) as r:
                return json.load(r)
        except OSError:
            time.sleep(3)
    raise SystemExit("server did not start")


meta = wait_for_server()
fhir = FhirClient(base)
say(f"server: {meta['software']['name']} {meta['software']['version']}, FHIR {meta['fhirVersion']}")
loaded = fhir.transaction(bundle())
say(f"loaded {len(loaded['entry'])} resources for {P}")

ids = lambda b: [e["resource"]["id"] for e in b["entry"]]  # noqa: E731
audit_params = sorted(p["name"] for r in meta["rest"][0]["resource"] if r["type"] == "AuditEvent"
                      for p in r.get("searchParam", []))
say(f"AuditEvent search parameters in the CapabilityStatement: {', '.join(audit_params)}")


class Clock:
    """The scenario runs on 20 and 21 March 2024, the week the provisional agreement text was published."""
    def __init__(self, start):
        self.now = start

    def at(self, when):
        self.now = when

    def __call__(self):
        self.now += timedelta(seconds=7)
        return self.now


clock = Clock(datetime(2024, 3, 20, 9, 10, tzinfo=timezone.utc))
gw = AccessGateway(fhir, clock=clock)

say("\n== 1. Before any restriction")
b = gw.search(GP, P, "Composition")
say(f"GP Practice B, Composition: {ids(b)}")
b = gw.search(HOSPITAL, P, "Observation")
say(f"Hospital A, Observation: {ids(b)} total {b['total']}")

clock.at(datetime(2024, 3, 20, 18, 40, tzinfo=timezone.utc))
say("\n== 2. The patient restricts test results for everyone except their GP (Article 8e)")
gw.restrictions[P] = Restriction(P, frozenset({C.TEST_RESULTS}), frozenset({"Organization/gp-b"}))
_, server_total = fhir.search_all("Observation", {"patient": P, "_count": 100, "_total": "accurate"})
b = gw.search(HOSPITAL, P, "Observation")
say(f"Hospital A, Observation: {ids(b)} total {b['total']}   (the server's own total: {server_total})")
b = gw.search(HOSPITAL, P, "DiagnosticReport")
say(f"Hospital A, DiagnosticReport: {ids(b)} total {b['total']}")
b = gw.search(GP, P, "Observation")
say(f"GP Practice B, Observation: {ids(b)} total {b['total']}")

clock.at(datetime(2024, 3, 21, 2, 15, tzinfo=timezone.utc))
say("\n== 3. Emergency access to restricted data (Article 7a(3))")
b = gw.search(ED, P, "Observation", emergency=True)
say(f"Hospital A emergency department, Observation: {ids(b)} total {b['total']}")

say("\n== 4. Finding the patient's access log on the server")
time.sleep(2)
counts = {}
for name, params in {"entity": {"entity": P}, "patient": {"patient": P},
                     "agent (hospital doctor)": {"agent": "Practitioner/dr-hosp-a"},
                     "date ge 2024-01-01": {"entity": P, "date": "ge2024-01-01"},
                     "purpose ETREAT": {"entity": P, "purpose": "ETREAT"}}.items():
    try:
        found, _ = fhir.search_all("AuditEvent", {**params, "_count": 100})
        counts[name] = len(found)
    except Exception as exc:  # report what the server said, keep going
        counts[name] = f"error: {exc}"[:160]
    say(f"AuditEvent?{name}: {counts[name]}")

say("\n== 5. Article 8f report for the patient")
events, _ = fhir.search_all("AuditEvent", {"entity": P, "_sort": "-date", "_count": 100})
report = render(rows(events))
say(report)
say("\nWith the individual withheld (a Member State restriction under Article 8f):")
say(render(rows(events, show_individual=False)))

sample = next(e for e in events if any(c["code"] == "ETREAT" for p in e["purposeOfEvent"] for c in p["coding"]))
(out / "audit-event-emergency.json").write_text(json.dumps(sample, indent=2))
(out / "experiments.txt").write_text("\n".join(log) + "\n")
(out / "results.json").write_text(json.dumps({"server": meta["software"], "auditevent_search": counts,
                                              "auditevent_search_params": audit_params,
                                              "events": len(events)}, indent=2))
