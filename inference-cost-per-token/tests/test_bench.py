"""Runs bench.py against a local fake OpenAI-compatible streaming server."""
import asyncio
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from bench import LevelResult, best_under_slo, percentile, run_level

TOKENS = 20
DELAY = 0.005


class FakeCompletions(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path != "/v1/completions" or not body.get("stream"):
            self.send_response(400)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if body["prompt"] == "fail":
            self.send_response(503)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        n = min(TOKENS, body["max_tokens"])
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()

        def send(obj):
            payload = f"data: {obj}\n\n".encode()
            self.wfile.write(f"{len(payload):x}\r\n".encode() + payload + b"\r\n")
            self.wfile.flush()

        # Two tokens per chunk, so the client must trust the usage count
        for _ in range(n // 2):
            time.sleep(DELAY)
            send(json.dumps({"choices": [{"text": "ab", "index": 0}]}))
        send(json.dumps({"choices": [], "usage": {"completion_tokens": n}}))
        send("[DONE]")
        self.wfile.write(b"0\r\n\r\n")


@pytest.fixture(scope="module")
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), FakeCompletions)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def test_run_level_counts_tokens_from_usage(server):
    lv = asyncio.run(run_level(server, "m", ["hello"], concurrency=4, requests=8, max_tokens=64))
    assert lv.failures == 0
    assert lv.output_tokens == 8 * TOKENS          # from usage, not the 10 chunks
    assert lv.ttft_p50 > 0 and lv.ttft_p95 >= lv.ttft_p50
    assert lv.itl_p95 >= DELAY * 0.5
    assert lv.tokens_per_second > 0


def test_run_level_records_failures(server):
    lv = asyncio.run(run_level(server, "m", ["hello", "fail"], concurrency=2, requests=4, max_tokens=8))
    assert lv.failures == 2
    assert lv.output_tokens == 2 * 8


def test_best_under_slo_picks_fastest_passing_level():
    def lv(c, tps, ttft, itl, fails=0):
        return LevelResult(c, 100, fails, 10.0, int(tps * 10), ttft, ttft, itl)
    levels = [lv(1, 100, 0.2, 0.02), lv(8, 600, 0.8, 0.05), lv(16, 900, 2.5, 0.07), lv(32, 950, 1.0, 0.2)]
    best = best_under_slo(levels, ttft_p95_max=2.0, itl_p95_max=0.1)
    assert best.concurrency == 8
    assert best_under_slo(levels, ttft_p95_max=0.1, itl_p95_max=0.1) is None
    levels.append(lv(12, 800, 1.0, 0.05, fails=3))
    assert best_under_slo(levels, 2.0, 0.1).concurrency == 8
    assert best_under_slo(levels, 2.0, 0.1, max_failure_rate=0.05).concurrency == 12


def test_percentile():
    assert percentile([], 95) == 0.0
    assert percentile([1, 2, 3, 4, 5], 50) == 3
    assert percentile([1, 2, 3, 4, 5], 100) == 5
