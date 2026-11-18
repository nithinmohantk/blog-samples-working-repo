"""A local stand-in for POST /v1/responses, for testing the client without an account or a model.

It returns the documented response shape and applies the documented prompt-caching rules to what it receives:
a prompt is served from the cache only when its first 1,024 tokens or more match an earlier prompt with the same
cache key, and the cached part is counted in steps of 128 tokens. It writes no code and answers no questions.
It is a model of the rules as published, not a copy of the service.
"""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from codex_budget.budget import CACHE_MINIMUM, CACHE_STEP

IMAGE_TOKENS = 765           # a fixed stand-in figure for one image; the real count depends on its size and detail
CONTEXT_WINDOW = 400_000


class StandIn:
    def __init__(self, encoder, fail_first_with_429: bool = False):
        self.encoder = encoder
        self.seen: dict[str, list[list[int]]] = {}
        self.requests: list[dict] = []
        self.authorizations: list[str] = []
        self._fail_next = fail_first_with_429
        handler = self._handler()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}/v1/"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()

    def _tokens(self, body: dict) -> tuple[list[int], int]:
        """The prompt in the order the service renders it: instructions, then each input item in turn."""
        tokens = self.encoder.encode(body.get("instructions") or "")
        images = 0
        for item in body["input"]:
            for part in item["content"]:
                if part["type"] == "input_text":
                    tokens += self.encoder.encode(part["text"])
                elif part["type"] == "input_image":
                    images += 1
                    tokens += [-1] * IMAGE_TOKENS
        return tokens, images

    def _cached(self, key: str, tokens: list[int]) -> int:
        best = 0
        for earlier in self.seen.get(key, []):
            shared = 0
            for a, b in zip(earlier, tokens):
                if a != b:
                    break
                shared += 1
            best = max(best, shared)
        if best < CACHE_MINIMUM:
            return 0
        return best - (best - CACHE_MINIMUM) % CACHE_STEP

    def _handler(self):
        stand_in = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def _send(self, status: int, payload: dict, headers: dict | None = None):
                data = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                for name, value in (headers or {}).items():
                    self.send_header(name, value)
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                if not self.path.endswith("/responses"):
                    return self._send(404, {"error": {"message": "not found", "type": "invalid_request_error"}})
                stand_in.authorizations.append(self.headers.get("Authorization", ""))
                if stand_in._fail_next:
                    stand_in._fail_next = False
                    return self._send(429, {"error": {"message": "Rate limit reached", "type": "rate_limit_error", "code": "rate_limit_exceeded"}}, {"retry-after": "0"})
                stand_in.requests.append(body)
                tokens, _ = stand_in._tokens(body)
                if len(tokens) + body.get("max_output_tokens", 0) > CONTEXT_WINDOW:
                    return self._send(400, {"error": {"message": "Your input exceeds the context window of this model.", "type": "invalid_request_error", "code": "context_length_exceeded"}})
                key = body.get("prompt_cache_key", "")
                cached = stand_in._cached(key, tokens)
                stand_in.seen.setdefault(key, []).append(tokens)
                output_tokens, reasoning = 420, 256
                self._send(200, {
                    "id": f"resp_{len(stand_in.requests):04d}", "object": "response", "created_at": int(time.time()), "status": "completed",
                    "model": body["model"], "parallel_tool_calls": True, "tool_choice": "auto", "tools": [],
                    "output": [{"type": "message", "id": "msg_0001", "role": "assistant", "status": "completed",
                                "content": [{"type": "output_text", "text": "stand-in answer", "annotations": []}]}],
                    "usage": {"input_tokens": len(tokens), "input_tokens_details": {"cached_tokens": cached},
                              "output_tokens": output_tokens, "output_tokens_details": {"reasoning_tokens": reasoning},
                              "total_tokens": len(tokens) + output_tokens},
                })

        return Handler
