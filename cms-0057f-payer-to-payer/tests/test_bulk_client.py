"""The export client against a small scripted server that behaves like a Bulk Data v1 endpoint."""
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "client"))
from bulk_export import BulkClient, ExportError  # noqa: E402


class Scripted(BaseHTTPRequestHandler):
    script: dict = {}
    seen: list = []

    def log_message(self, *args):
        pass

    def do_GET(self):
        Scripted.seen.append((self.path, dict(self.headers)))
        base = f"http://127.0.0.1:{self.server.server_port}"
        if "$export" in self.path:
            code = Scripted.script.get("kickoff", 202)
            self.send_response(code)
            if code == 202:
                self.send_header("Content-Location", f"{base}/status/1")
            self.end_headers()
            return
        if self.path.startswith("/status/"):
            pending = Scripted.script.setdefault("pending", 2)
            if pending:
                Scripted.script["pending"] = pending - 1
                self.send_response(202)
                self.send_header("Retry-After", "1")
                self.send_header("X-Progress", "in progress")
                self.end_headers()
                return
            manifest = {"transactionTime": "2024-01-19T10:00:00Z", "request": self.path, "requiresAccessToken": False,
                        "output": [{"type": "Patient", "url": f"{base}/files/p.ndjson"},
                                   {"type": "ExplanationOfBenefit", "url": f"{base}/files/e.ndjson"}],
                        "error": Scripted.script.get("errors", [])}
            body = json.dumps(manifest).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/files/p.ndjson":
            body = b'{"resourceType":"Patient","id":"m1"}\n{"resourceType":"Patient","id":"m2"}\n'
        else:
            body = b'{"resourceType":"ExplanationOfBenefit","id":"e1"}\n\n'
        self.send_response(200)
        self.send_header("Content-Type", "application/fhir+ndjson")
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def server():
    Scripted.script, Scripted.seen = {}, []
    httpd = HTTPServer(("127.0.0.1", 0), Scripted)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()


def test_full_export_honours_retry_after(server):
    waits = []
    client = BulkClient(server, sleep=waits.append, token_provider=lambda: "t0ken")
    result = client.export("p2p-optin", ["Patient", "ExplanationOfBenefit"], since="2019-01-19T00:00:00Z")
    assert result.counts() == {"ExplanationOfBenefit": 1, "Patient": 2}
    assert result.polls == 3
    assert len(waits) == 2 and all(1.0 <= w <= 1.1 for w in waits)
    kickoff_path, kickoff_headers = Scripted.seen[0]
    assert "_type=Patient%2CExplanationOfBenefit" in kickoff_path and "_since=2019-01-19" in kickoff_path
    assert kickoff_headers["Prefer"] == "respond-async"
    assert all(h["Authorization"] == "Bearer t0ken" for _, h in Scripted.seen)


def test_kickoff_refusal_is_an_error(server):
    Scripted.script["kickoff"] = 400
    with pytest.raises(ExportError, match="kick-off returned 400"):
        BulkClient(server, sleep=lambda s: None).export("g", ["Patient"])


def test_manifest_errors_stop_the_download(server):
    Scripted.script["errors"] = [{"type": "OperationOutcome", "url": "x"}]
    with pytest.raises(ExportError, match="export reported errors"):
        BulkClient(server, sleep=lambda s: None).export("g", ["Patient"])


def test_gives_up_after_max_wait(server):
    Scripted.script["pending"] = 100
    with pytest.raises(ExportError, match="not complete"):
        BulkClient(server, sleep=lambda s: None, max_wait_seconds=0.5).export("g", ["Patient"])
