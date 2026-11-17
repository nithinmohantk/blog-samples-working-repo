"""Loads the synthetic payer data into a HAPI FHIR server and runs the payer-to-payer export four ways.

    python tools/run_experiments.py http://localhost:8080/fhir <output dir>
"""
import json
import sys
import time
import urllib.request
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from bulk_export import BulkClient  # noqa: E402
from service_window import apply_window, five_years_before  # noqa: E402

base, out = sys.argv[1], Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)
REQUEST_DATE = date(2024, 1, 19)
TYPES = ["Patient", "Coverage", "ExplanationOfBenefit", "Encounter", "Condition", "Observation"]


def wait_for_server(seconds=300):
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{base}/metadata", timeout=10) as r:
                return json.load(r)
        except OSError:
            time.sleep(3)
    raise SystemExit("server did not start")


def load():
    body = (ROOT / "data" / "seed-bundle.json").read_bytes()
    req = urllib.request.Request(base, data=body, method="POST", headers={"Content-Type": "application/fhir+json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        resp = json.load(r)
    return Counter(e["response"]["status"].split()[0] for e in resp["entry"])


def patients_in(result):
    refs = set()
    for items in result.resources.values():
        for r in items:
            if r["resourceType"] == "Patient":
                refs.add(r["id"])
            for key in ("patient", "subject", "beneficiary"):
                ref = r.get(key, {}).get("reference", "")
                if ref.startswith("Patient/"):
                    refs.add(ref.split("/")[1])
    return sorted(refs)


meta = wait_for_server()
report = {"server": meta.get("software", {}), "fhirVersion": meta.get("fhirVersion"), "request_date": str(REQUEST_DATE),
          "window_starts": str(five_years_before(REQUEST_DATE)), "load": dict(load())}
client = BulkClient(base, max_wait_seconds=300)
runs = {
    "plain": {},
    "since_five_years": {"since": f"{five_years_before(REQUEST_DATE)}T00:00:00Z"},
    "type_filter": {"type_filters": [f"ExplanationOfBenefit?service-date=ge{five_years_before(REQUEST_DATE)}"]},
}
for name, kwargs in runs.items():
    try:
        result = client.export("p2p-optin", TYPES, **kwargs)
        report[name] = {"counts": result.counts(), "patients": patients_in(result), "polls": result.polls,
                        "manifest_request": result.manifest.get("request"),
                        "requiresAccessToken": result.manifest.get("requiresAccessToken")}
        if name == "plain":
            plain = result
    except Exception as exc:  # recorded, not fatal: the point is to see what the server does
        report[name] = {"error": f"{type(exc).__name__}: {exc}"}
    time.sleep(2)

decisions = apply_window(plain.resources, REQUEST_DATE)
report["window"] = {
    "kept": dict(Counter(d.resource_type for d in decisions if d.keep)),
    "reasons": dict(Counter(d.reason for d in decisions)),
    "held_or_dropped": sorted(f"{d.resource_type}/{d.resource_id} {d.service_date or '-'}: {d.reason}"
                              for d in decisions if not d.keep),
}
(out / "experiments.json").write_text(json.dumps(report, indent=2) + "\n")

lines = [f"server {report['server'].get('name')} {report['server'].get('version')}, FHIR {report['fhirVersion']}",
         f"request date {REQUEST_DATE}, window starts {report['window_starts']}", f"loaded {report['load']}"]
for name in runs:
    r = report[name]
    lines.append(f"{name:<17} " + (r["error"] if "error" in r else f"{r['counts']} patients={r['patients']}"))
lines.append(f"after the window   kept {report['window']['kept']}")
lines += [f"  not sent: {x}" for x in report["window"]["held_or_dropped"]]
(out / "experiments.txt").write_text("\n".join(lines) + "\n")
print("\n".join(lines))
