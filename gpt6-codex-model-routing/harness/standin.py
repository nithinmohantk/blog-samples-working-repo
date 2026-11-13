"""A local stand-in for the Responses API, for watching what the Codex CLI sends.

It speaks the streaming form of POST /v1/responses that the CLI uses. It does not think: it plays a script. Each
scripted step is either a shell command for Codex to run or a final message. Every request the CLI makes is
recorded, so the requests can be compared afterwards. Usage figures in the replies are counted from the request
with tiktoken, so the CLI sees context sizes close to what a real service would report.

    python standin.py <port file> <record file> <script.json>
"""
from __future__ import annotations

import hashlib
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import tiktoken

encoder = tiktoken.get_encoding("o200k_base")
port_file, record_file, script_file = sys.argv[1:4]
script: list[dict] = json.load(open(script_file, encoding="utf-8"))
lock = threading.Lock()
state = {"step": 0, "requests": 0}
SHELL_NAMES = ("exec_command", "shell", "shell_command", "local_shell", "container.exec", "unified_exec")


def count(value) -> int:
    return len(encoder.encode(value if isinstance(value, str) else json.dumps(value, ensure_ascii=False), disallowed_special=()))


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:12]


def outline(tool, depth: int = 0) -> list[str]:
    """Names, types and parameter names of a tool declaration and anything nested in it. No descriptions."""
    if not isinstance(tool, dict):
        return []
    parameters = tool.get("parameters") or {}
    line = "  " * depth + f"{tool.get('type')} {tool.get('name')} keys={sorted(tool)} params={sorted((parameters.get('properties') or {}))} required={parameters.get('required')}"
    lines = [line]
    for child in tool.get("tools") or []:
        lines += outline(child, depth + 1)
    return lines


def shell_call(tools: list[dict], command: str) -> dict | None:
    """Builds a call to whichever shell tool the CLI declared, in the argument shape that tool's schema asks for."""
    for tool in tools:
        name = tool.get("name") or tool.get("type")
        if name not in SHELL_NAMES:
            continue
        if tool.get("type") == "local_shell":
            return {"type": "local_shell_call", "call_id": f"call_{state['step']}", "status": "completed",
                    "action": {"type": "exec", "command": ["bash", "-lc", command]}}
        properties = (tool.get("parameters") or {}).get("properties", {})
        if "cmd" in properties:
            arguments = {"cmd": command}
        elif properties.get("command", {}).get("type") == "array":
            arguments = {"command": ["bash", "-lc", command]}
        else:
            arguments = {"command": command}
        return {"type": "function_call", "call_id": f"call_{state['step']}", "name": name, "arguments": json.dumps(arguments), "status": "completed"}
    return None


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_):
        pass

    def _json(self, status: int, payload: dict):
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _record(self, entry: dict):
        with lock, open(record_file, "a", encoding="utf-8") as out:
            out.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def do_GET(self):
        self._record({"method": "GET", "path": self.path})
        self._json(404, {"error": {"message": "not found", "type": "invalid_request_error"}})

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        encoding = self.headers.get("Content-Encoding", "")
        try:
            body = json.loads(raw)
        except ValueError:
            self._record({"method": "POST", "path": self.path, "unparsed_bytes": len(raw), "content_encoding": encoding})
            return self._json(400, {"error": {"message": "the stand-in reads plain JSON only", "type": "invalid_request_error"}})
        if not self.path.rstrip("/").endswith("/responses"):
            self._record({"method": "POST", "path": self.path, "keys": sorted(body) if isinstance(body, dict) else None})
            return self._json(404, {"error": {"message": "not found", "type": "invalid_request_error"}})

        with lock:
            state["requests"] += 1
            number = state["requests"]
            step = script[state["step"]] if state["step"] < len(script) else {"message": "Done."}
            state["step"] += 1
        items = body.get("input") if isinstance(body.get("input"), list) else [body.get("input")]
        # This CLI version declares its tools in an input item, not in a top-level field.
        tools = list(body.get("tools") or [])
        for item in items:
            if isinstance(item, dict) and item.get("type") == "additional_tools":
                tools += item.get("tools") or []
        instructions_tokens, tools_tokens, input_tokens = count(body.get("instructions") or ""), count(tools), count(items)
        prompt_tokens = instructions_tokens + tools_tokens + input_tokens
        self._record({
            "method": "POST", "path": self.path, "request": number,
            "authorization": "Bearer <present>" if self.headers.get("Authorization", "").startswith("Bearer ") else "absent",
            "top_level_keys": sorted(body),
            "model": body.get("model"), "reasoning": body.get("reasoning"), "service_tier": body.get("service_tier"),
            "stream": body.get("stream"), "store": body.get("store"), "include": body.get("include"),
            "prompt_cache_key": bool(body.get("prompt_cache_key")), "prompt_cache_key_digest": digest(body.get("prompt_cache_key")),
            "parallel_tool_calls": body.get("parallel_tool_calls"), "tool_choice": body.get("tool_choice"),
            "text": body.get("text"), "max_output_tokens": body.get("max_output_tokens"),
            "instructions_tokens": instructions_tokens, "instructions_digest": digest(body.get("instructions")),
            "tools_tokens": tools_tokens, "tools_digest": digest(tools),
            "tools": [{"type": tool.get("type"), "name": tool.get("name"), "parameters": sorted(((tool.get("parameters") or {}).get("properties") or {})),
                       "required": (tool.get("parameters") or {}).get("required"), "keys": sorted(tool)} for tool in tools],
            "tool_outline": [line for tool in tools for line in outline(tool)],
            "debug_exec": next(({"format": t.get("format"), "description": (t.get("description") or "")[:6000]} for ns in tools for t in (ns.get("tools") or []) if t.get("name") == "exec"), None) if number == 1 else None,
            "item_keys": [sorted(item) if isinstance(item, dict) else None for item in items],
            "item_starts": [json.dumps(item.get("content") if isinstance(item, dict) and "content" in item else item, ensure_ascii=False)[:90] for item in items],
            "input_items": len(items), "input_tokens": input_tokens,
            "item_digests": [digest(item) for item in items],
            "item_kinds": [(item.get("type") or "message") + (":" + item["role"] if isinstance(item, dict) and item.get("role") else "") if isinstance(item, dict) else "text" for item in items],
            "item_tokens": [count(item) for item in items],
            "prompt_tokens": prompt_tokens,
            "headers": sorted(name.lower() for name in self.headers if name.lower().startswith(("openai", "x-", "session", "conversation", "originator", "version"))),
        })

        output_item = shell_call(tools, step["shell"]) if "shell" in step else None
        if "tool" in step:
            output_item = {"type": "function_call", "call_id": f"call_{state['step']}", "name": step["tool"], "arguments": json.dumps(step["arguments"]), "status": "completed"}
        if output_item is None:
            text = step.get("message", "The stand-in found no shell tool to call.")
            output_item = {"type": "message", "role": "assistant", "status": "completed", "content": [{"type": "output_text", "text": text, "annotations": []}]}
        output_item["id"] = ("msg_" if output_item["type"] == "message" else "fc_") + f"{number:04d}"
        output_tokens = int(step.get("output_tokens", 200))
        usage = {"input_tokens": prompt_tokens, "input_tokens_details": {"cached_tokens": 0}, "output_tokens": output_tokens,
                 "output_tokens_details": {"reasoning_tokens": 0}, "total_tokens": prompt_tokens + output_tokens}
        response = {"id": f"resp_{number:04d}", "object": "response", "created_at": 1790000000 + number, "status": "in_progress", "model": body.get("model"), "output": []}
        events = [
            {"type": "response.created", "response": response},
            {"type": "response.output_item.added", "output_index": 0, "item": {**output_item, "status": "in_progress"}},
        ]
        if output_item["type"] == "message":
            events.append({"type": "response.output_text.delta", "item_id": output_item["id"], "output_index": 0, "content_index": 0, "delta": output_item["content"][0]["text"]})
        events += [
            {"type": "response.output_item.done", "output_index": 0, "item": output_item},
            {"type": "response.completed", "response": {**response, "status": "completed", "output": [output_item], "usage": usage}},
        ]
        payload = "".join(f"event: {event['type']}\ndata: {json.dumps({**event, 'sequence_number': index})}\n\n" for index, event in enumerate(events)).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
open(port_file, "w").write(str(server.server_address[1]))
server.serve_forever()
