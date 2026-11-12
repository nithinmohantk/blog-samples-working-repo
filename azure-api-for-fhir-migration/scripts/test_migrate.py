"""Tests for migrate.py against a local stand-in for the two Azure services.

The stand-in implements the request and response shapes Microsoft documents for $export on Azure API for
FHIR and $import on the FHIR service. It is not either service: it proves the script sends what the
documentation asks for and handles the documented answers, not that Azure accepts it.

    python test_migrate.py
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import migrate

STATE: dict = {}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args) -> None:  # keep test output quiet
        pass

    def _send(self, status: int, body: dict | None = None, **headers: str) -> None:
        payload = json.dumps(body).encode() if body is not None else b""
        self.send_response(status)
        for name, value in headers.items():
            self.send_header(name.replace("_", "-"), value)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        url = urlparse(self.path)
        base = f"http://{self.headers['Host']}"
        STATE.setdefault("tokens", []).append(self.headers.get("Authorization"))
        if url.path == "/source/$export":
            STATE["export_query"] = {k: v[0] for k, v in parse_qs(url.query).items()}
            STATE["export_headers"] = (self.headers.get("Accept"), self.headers.get("Prefer"))
            self._send(202, Content_Location=f"{base}/source/_operations/export/1")
        elif url.path == "/source/_operations/export/1":
            STATE["export_polls"] = STATE.get("export_polls", 0) + 1
            if STATE["export_polls"] < 3:
                self._send(202, Retry_After="0")
            else:
                self._send(200, STATE["manifest"])
        elif url.path == "/target/_operations/import/1":
            STATE["import_polls"] = STATE.get("import_polls", 0) + 1
            if STATE.get("import_fatal"):
                self._send(500, {"diagnostics": "SECRET detail"})
            elif STATE["import_polls"] < 2:
                self._send(202)
            else:
                self._send(200, STATE["import_result"])
        else:
            self._send(404)

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if urlparse(self.path).path == "/target/$import":
            STATE["import_body"] = body
            STATE["import_headers"] = (self.headers.get("Content-Type"), self.headers.get("Prefer"))
            names = [p["name"] for p in body.get("parameter", [])]
            if body.get("resourceType") != "Parameters" or "inputFormat" not in names or "input" not in names:
                self._send(400)
            else:
                self._send(202, Content_Location=f"http://{self.headers['Host']}/target/_operations/import/1")
        else:
            self._send(404)


MANIFEST = {
    "transactionTime": "2026-08-22T22:00:00Z", "requiresAccessToken": False, "error": [],
    "output": [
        {"type": "Patient", "url": "https://stmig.blob.core.windows.net/migration-2026-08/Patient-1.ndjson"},
        {"type": "Observation", "url": "https://stmig.blob.core.windows.net/migration-2026-08/Observation-1.ndjson"},
        {"type": "Observation", "url": "https://stmig.blob.core.windows.net/migration-2026-08/Observation-2.ndjson"},
        {"type": "SearchParameter", "url": "https://stmig.blob.core.windows.net/migration-2026-08/SearchParameter-1.ndjson"},
    ],
}
RESULT_OK = {"transactionTime": "2026-08-22T22:05:00Z", "output": [
    {"type": "Patient", "count": 5, "inputUrl": MANIFEST["output"][0]["url"]},
    {"type": "Observation", "count": 5000, "inputUrl": MANIFEST["output"][1]["url"]},
    {"type": "Observation", "count": 1200, "inputUrl": MANIFEST["output"][2]["url"]}]}
RESULT_PARTIAL = {**RESULT_OK, "error": [{"type": "OperationOutcome", "count": 51, "inputUrl": MANIFEST["output"][2]["url"],
                                           "url": "https://stmig.blob.core.windows.net/fhirlogs/Observation-errors.ndjson"}]}


def run(*extra: str, manifest=MANIFEST, result=RESULT_OK, fatal=False) -> int:
    STATE.clear()
    STATE.update(manifest=manifest, import_result=result, import_fatal=fatal)
    return migrate.main(["--source", f"{BASE}/source", "--target", f"{BASE}/target", "--container", "migration-2026-08",
                         "--poll-seconds", "0", *extra], token_provider=lambda base: "token-for-" + base.rsplit("/", 1)[-1])


def check(condition: bool, what: str) -> None:
    RESULTS.append(condition)
    print(f"{'PASS' if condition else 'FAIL'}  {what}")


server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{server.server_address[1]}"
RESULTS: list[bool] = []

code = run("--till", "2026-08-22T22:00:00Z", "--history", "--deleted")
check(code == 0, "a clean export and import exits 0")
check(STATE["export_query"] == {"_container": "migration-2026-08", "_till": "2026-08-22T22:00:00Z",
                                "includeAssociatedData": "_history,_deleted"}, "export asks for the container, the cut-off, history and soft deletes")
check(STATE["export_headers"] == ("application/fhir+json", "respond-async"), "export sends Accept and Prefer: respond-async")
check(STATE["export_polls"] == 3 and STATE["import_polls"] == 2, "both operations are polled until HTTP 200")
body = STATE["import_body"]
by_name = {p["name"]: p for p in body["parameter"] if p["name"] != "input"}
inputs = [{part["name"]: part.get("valueString") or part.get("valueUri") for part in p["part"]} for p in body["parameter"] if p["name"] == "input"]
check(by_name["inputFormat"]["valueString"] == "application/fhir+ndjson" and by_name["mode"]["valueString"] == "IncrementalLoad",
      "import declares NDJSON and IncrementalLoad")
check(inputs == [{"type": o["type"], "url": o["url"]} for o in MANIFEST["output"][:3]], "one input per exported file, SearchParameter left out")
check(STATE["import_headers"] == ("application/fhir+json", "respond-async"), "import sends Content-Type and Prefer: respond-async")
check("Bearer token-for-source" in STATE["tokens"] and "Bearer token-for-target" in STATE["tokens"], "each service gets a token for its own audience")

run("--since", "2026-08-22T22:00:00Z", "--types", "Observation,Patient")
check(STATE["export_query"] == {"_container": "migration-2026-08", "_since": "2026-08-22T22:00:00Z", "_type": "Observation,Patient"},
      "a delta run passes _since and _type and no history flag")

check(run(result=RESULT_PARTIAL) == 1, "an import with rejected resources exits 1")
summary = migrate.summarise_import(RESULT_PARTIAL)
check(summary["loaded"] == {"Patient": 5, "Observation": 6200} and summary["failedTotal"] == 51
      and summary["failed"][0]["errorFile"].endswith("Observation-errors.ndjson"), "the summary adds up counts and points at the error file")

check(run(manifest={**MANIFEST, "error": [{"type": "OperationOutcome", "url": "https://x/err.ndjson"}]}) == 2 and "import_body" not in STATE,
      "an export with errors stops before anything is imported")
check(run(manifest={**MANIFEST, "output": []}) == 2, "an empty export stops the run")
check(run(fatal=True) == 2, "a fatal import status exits 2")

try:
    migrate.main(["--source", "s", "--target", "t", "--container", "c", "--mode", "InitialLoad", "--history"], token_provider=lambda b: "t")
    refused = False
except SystemExit as stop:
    refused = stop.code == 2
check(refused, "InitialLoad with --history is refused before any request")

try:
    migrate.build_import_parameters({"output": [{"type": "Patient", "url": f"https://x/{i}.ndjson"} for i in range(10_001)]})
    too_many = False
except migrate.MigrationError:
    too_many = True
check(too_many, "more than 10,000 files are refused")

server.shutdown()
print(f"\n{sum(RESULTS)} of {len(RESULTS)} checks passed")
raise SystemExit(0 if all(RESULTS) else 1)
