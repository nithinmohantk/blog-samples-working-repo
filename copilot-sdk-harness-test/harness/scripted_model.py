"""A scripted stand-in for an OpenAI-compatible chat completions endpoint (no real model, no cost).

The 'model' name in each request selects a script. A script is a function from the request's
messages to the next reply: either text, or a list of tool calls. Every request is logged so a
test can see exactly what the harness sent back to the model (tool results, error text, sizes).
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable

Reply = dict[str, Any]   # {"text": str} or {"tool_calls": [(name, args_dict_or_raw_str), ...]}
Script = Callable[[list[dict[str, Any]], dict[str, Any]], Reply]

SCRIPTS: dict[str, Script] = {}
LOG: list[dict[str, Any]] = []


def script(name: str):
    def deco(fn: Script) -> Script:
        SCRIPTS[name] = fn
        return fn
    return deco


def _completion(model: str, reply: Reply) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if "tool_calls" in reply:
        calls = [{"id": f"call_{uuid.uuid4().hex[:12]}", "type": "function",
                  "function": {"name": n, "arguments": a if isinstance(a, str) else json.dumps(a)}}
                 for n, a in reply["tool_calls"]]
        msg = {"role": "assistant", "content": None, "tool_calls": calls}
        finish = "tool_calls"
    else:
        calls, msg, finish = [], {"role": "assistant", "content": reply["text"]}, "stop"
    body = {"id": f"chatcmpl-{uuid.uuid4().hex[:12]}", "object": "chat.completion", "created": int(time.time()),
            "model": model, "choices": [{"index": 0, "message": msg, "finish_reason": finish}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}}
    chunks = []
    base = {"id": body["id"], "object": "chat.completion.chunk", "created": body["created"], "model": model}
    if calls:
        for i, c in enumerate(calls):
            chunks.append({**base, "choices": [{"index": 0, "delta": {"role": "assistant", "tool_calls": [
                {"index": i, "id": c["id"], "type": "function",
                 "function": {"name": c["function"]["name"], "arguments": c["function"]["arguments"]}}]},
                "finish_reason": None}]})
    else:
        chunks.append({**base, "choices": [{"index": 0, "delta": {"role": "assistant", "content": reply["text"]},
                                            "finish_reason": None}]})
    chunks.append({**base, "choices": [{"index": 0, "delta": {}, "finish_reason": finish}],
                   "usage": body["usage"]})
    return body, chunks


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a: Any) -> None:  # quiet
        pass

    def do_GET(self) -> None:
        if self.path.rstrip("/").endswith("/models"):
            data = {"object": "list", "data": [{"id": k, "object": "model", "owned_by": "lab"} for k in SCRIPTS]}
            self._json(200, data)
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self) -> None:
        length = int(self.headers.get("content-length", 0))
        req = json.loads(self.rfile.read(length) or b"{}")
        model = req.get("model", "")
        LOG.append({"path": self.path, "model": model, "messages": req.get("messages", []),
                    "tools": [t.get("function", {}).get("name") for t in req.get("tools", [])], "tool_defs": req.get("tools", []),
                    "stream": req.get("stream", False), "t": time.time(), "raw_keys": sorted(req)})
        fn = SCRIPTS.get(model) or SCRIPTS.get(model.split("/")[-1])
        if fn is None:
            self._json(404, {"error": {"message": f"unknown model {model}", "type": "invalid_request_error"}})
            return
        try:
            reply = fn(req.get("messages", []), req)
        except Exception as e:  # a script can simulate an endpoint failure by raising
            status = getattr(e, "status", 500)
            self._json(status, {"error": {"message": str(e), "type": "server_error"}})
            return
        body, chunks = _completion(model, reply)
        if req.get("stream"):
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.end_headers()
            for c in chunks:
                self.wfile.write(f"data: {json.dumps(c)}\n\n".encode())
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        else:
            self._json(200, body)

    def _json(self, status: int, data: Any) -> None:
        raw = json.dumps(data).encode()
        try:
            self.send_response(status)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError):
            pass  # the client aborted the request (for example a session abort)


def serve(port: int = 0) -> tuple[ThreadingHTTPServer, str]:
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/v1"


def tool_results(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [m for m in messages if m.get("role") == "tool"]
