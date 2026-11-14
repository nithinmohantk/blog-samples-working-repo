"""A scripted stand-in for a hosted model, speaking two wire protocols: OpenAI Chat Completions and the Gemini API.

It does not think. A script says what the "model" returns for the first request, the second, and so on: tool
calls, text, or an HTTP error. Every request is kept so that what each framework sent can be compared.
"""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class StandIn:
    def __init__(self, script: list[dict]):
        self.script = script
        self.requests: list[dict] = []        # {"protocol", "path", "headers", "body", "step"}
        self._lock = threading.Lock()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.server.handle_error = lambda *_: None    # a client that hangs up mid-run is not worth a traceback
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def openai_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/v1"

    @property
    def gemini_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def _next(self, protocol: str, path: str, headers: dict, body: dict) -> tuple[int, dict]:
        with self._lock:
            number = len(self.requests)
            # A script whose last step has "repeat" keeps returning that step for ever.
            step = self.script[number] if number < len(self.script) else (self.script[-1] if self.script[-1].get("repeat") else {"text": "Done."})
            self.requests.append({"protocol": protocol, "path": path, "headers": headers, "body": body, "step": step})
            return number, step

    def _handler(self):
        stand_in = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_):
                pass

            def _send(self, status: int, payload: bytes, content_type: str = "application/json", extra: dict | None = None):
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(payload)))
                for name, value in (extra or {}).items():
                    self.send_header(name, value)
                self.end_headers()
                self.wfile.write(payload)

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")
                headers = {name.lower(): value for name, value in self.headers.items()}
                gemini = ":generateContent" in self.path or ":streamGenerateContent" in self.path
                if not gemini and not self.path.endswith("/chat/completions"):
                    return self._send(404, json.dumps({"error": {"message": f"the stand-in does not serve {self.path}", "type": "invalid_request_error"}}).encode())
                number, step = stand_in._next("gemini" if gemini else "chat", self.path, headers, body)
                if "status" in step:
                    error = {"error": {"message": step.get("message", "scripted failure"), "type": "server_error", "code": step["status"], "status": "UNAVAILABLE"}}
                    return self._send(step["status"], json.dumps(error).encode(), extra={"retry-after": "0", "retry-after-ms": "0"})
                if gemini:
                    return self._gemini(number, step, stream=":streamGenerateContent" in self.path)
                return self._chat(number, step, body)

            # ---- OpenAI Chat Completions ----
            def _chat(self, number: int, step: dict, body: dict):
                calls = [{"id": f"call_{number}_{index}", "type": "function", "function": {"name": name, "arguments": arguments if isinstance(arguments, str) else json.dumps(arguments)}}
                         for index, (name, arguments) in enumerate(step.get("calls", []))]
                message = {"role": "assistant", "content": step.get("text") if not calls else None}
                if calls:
                    message["tool_calls"] = calls
                finish = "tool_calls" if calls else "stop"
                usage = {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}
                base = {"id": f"chatcmpl-{number:04d}", "created": int(time.time()), "model": body.get("model", "stand-in")}
                if not body.get("stream"):
                    payload = {**base, "object": "chat.completion", "choices": [{"index": 0, "message": message, "finish_reason": finish}], "usage": usage}
                    return self._send(200, json.dumps(payload).encode())
                delta = {"role": "assistant", "content": message["content"] or ""}
                if calls:
                    delta["tool_calls"] = [{"index": index, **call} for index, call in enumerate(calls)]
                chunks = [
                    {**base, "object": "chat.completion.chunk", "choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
                    {**base, "object": "chat.completion.chunk", "choices": [{"index": 0, "delta": {}, "finish_reason": finish}]},
                    {**base, "object": "chat.completion.chunk", "choices": [], "usage": usage},
                ]
                payload = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n"
                return self._send(200, payload.encode(), "text/event-stream")

            # ---- Gemini API ----
            def _gemini(self, number: int, step: dict, stream: bool):
                parts = [{"functionCall": {"id": f"call_{number}_{index}", "name": name, "args": json.loads(arguments) if isinstance(arguments, str) else arguments}}
                         for index, (name, arguments) in enumerate(step.get("calls", []))]
                if not parts:
                    parts = [{"text": step.get("text", "")}]
                payload = {"candidates": [{"content": {"role": "model", "parts": parts}, "finishReason": "STOP", "index": 0}],
                           "usageMetadata": {"promptTokenCount": 100, "candidatesTokenCount": 20, "totalTokenCount": 120}, "modelVersion": "stand-in", "responseId": f"resp-{number:04d}"}
                if stream:
                    return self._send(200, f"data: {json.dumps(payload)}\n\n".encode(), "text/event-stream")
                return self._send(200, json.dumps(payload).encode())

        return Handler
