"""A small in-memory stand-in for a FHIR R4 server, for local runs and unit tests. Not a FHIR server.

It knows: transaction bundles of PUTs, create, read, and search by patient/subject, category, code,
family and _id, with _include=Observation:subject, _revinclude=<Type>:subject|patient and
Patient/<id>/$everything. Anything else in a query is answered with 400, where a real server may accept it.
"""
from __future__ import annotations

import json
import sys
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl, urlsplit

STORE: dict[tuple[str, str], dict] = {}
KNOWN = {"patient", "subject", "category", "code", "family", "_id", "_include", "_revinclude", "_count", "_sort"}


def subject_of(resource: dict) -> str:
    return (resource.get("subject") or {}).get("reference", "")


def matches(resource: dict, name: str, value: str) -> bool:
    if name in ("patient", "subject"):
        return subject_of(resource) == "Patient/" + value.removeprefix("Patient/")
    if name == "_id":
        return resource["id"] in value.split(",")
    if name == "family":
        return any(n.get("family", "").lower().startswith(value.lower()) for n in resource.get("name", []))
    if name in ("category", "code"):
        concepts = resource.get(name, []) if name == "category" else [resource.get("code", {})]
        held = {f"{c.get('system')}|{c.get('code')}" for concept in concepts for c in concept.get("coding", [])} | {c.get("code") for concept in concepts for c in concept.get("coding", [])}
        return any(wanted in held for wanted in value.split(","))
    return True


def search(resource_type: str, query: list[tuple[str, str]]) -> tuple[int, dict]:
    unknown = [name for name, _ in query if name not in KNOWN]
    if unknown:
        return 400, {"resourceType": "OperationOutcome", "issue": [{"severity": "error", "diagnostics": f"the stand-in does not support {unknown}"}]}
    found = [r for (kind, _), r in STORE.items() if kind == resource_type and all(matches(r, n, v) for n, v in query if not n.startswith("_") or n == "_id")]
    extra: list[dict] = []
    for name, value in query:
        if name == "_include" and value == "Observation:subject":
            extra += [STORE[("Patient", subject_of(r).removeprefix("Patient/"))] for r in found if ("Patient", subject_of(r).removeprefix("Patient/")) in STORE]
        if name == "_revinclude":
            kind = value.split(":")[0]
            extra += [r for (k, _), r in STORE.items() if k == kind and subject_of(r) in {f"Patient/{p['id']}" for p in found}]
    unique = {(r["resourceType"], r["id"]): r for r in found + extra}
    return 200, {"resourceType": "Bundle", "type": "searchset", "entry": [{"resource": r} for r in unique.values()]}


class Handler(BaseHTTPRequestHandler):
    def reply(self, status: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/fhir+json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        url = urlsplit(self.path)
        parts = [p for p in url.path.split("/") if p][1:]  # drop the /fhir prefix
        if parts == ["metadata"]:
            return self.reply(200, {"resourceType": "CapabilityStatement", "fhirVersion": "4.0.1", "software": {"name": "stand-in"}})
        if len(parts) == 3 and parts[0] == "Patient" and parts[2] == "$everything":
            found = [r for r in STORE.values() if r["id"] == parts[1] and r["resourceType"] == "Patient" or subject_of(r) == f"Patient/{parts[1]}"]
            return self.reply(200, {"resourceType": "Bundle", "type": "searchset", "entry": [{"resource": r} for r in found]})
        if len(parts) == 2:
            resource = STORE.get((parts[0], parts[1]))
            return self.reply(200, resource) if resource else self.reply(404, {"resourceType": "OperationOutcome"})
        if len(parts) == 1:
            return self.reply(*search(parts[0], parse_qsl(url.query)))
        self.reply(400, {"resourceType": "OperationOutcome"})

    def do_POST(self) -> None:  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
        if body.get("resourceType") == "Bundle":
            for entry in body["entry"]:
                STORE[(entry["resource"]["resourceType"], entry["resource"]["id"])] = entry["resource"]
            return self.reply(200, {"resourceType": "Bundle", "type": "transaction-response"})
        body["id"] = "new-" + uuid.uuid4().hex[:12]
        STORE[(body["resourceType"], body["id"])] = body
        self.reply(201, body)

    def log_message(self, *args: object) -> None:
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), Handler).serve_forever()
