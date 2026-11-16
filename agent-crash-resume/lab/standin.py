"""A scripted stand-in for a hosted model, speaking OpenAI Chat Completions and the Gemini API.

It does not think, and it keeps no memory between requests. It reads the conversation it is sent and
answers with the next step of one fixed plan: reserve the stock, charge the card, send the confirmation,
then say it is done. The next step is the first tool that has no result in the conversation. That is how
a sensible model behaves, and it makes the stand-in an honest probe: after a crash, what it asks for
depends only on what the framework chose to send it.

    python lab/standin.py <port file> <request log>

Like the real Chat Completions API, it refuses a conversation in which a tool call has no tool message
answering it. Each tool call gets a fresh random id, as a real model would give it.
"""
from __future__ import annotations

import json
import sys
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ORDER = {"order_id": "O-1001", "sku": "FAS-0012", "quantity": 3, "amount_cents": 3750, "email": "buyer@example.com"}
PLAN = [
    ("reserve_stock", {"order_id": ORDER["order_id"], "sku": ORDER["sku"], "quantity": ORDER["quantity"]}),
    ("charge_card", {"order_id": ORDER["order_id"], "amount_cents": ORDER["amount_cents"]}),
    ("send_confirmation", {"order_id": ORDER["order_id"], "email": ORDER["email"]}),
]
DONE = "Order O-1001 is placed: stock reserved, card charged, confirmation sent."


def read_chat(body: dict) -> tuple[set[str], list[str], int]:
    """Tools with a result, tool calls left unanswered, and how many user messages there are."""
    called: dict[str, str] = {}
    answered: set[str] = set()
    users = 0
    for message in body.get("messages", []):
        if message.get("role") == "user":
            users += 1
        for call in message.get("tool_calls") or []:
            called[call["id"]] = call["function"]["name"]
        if message.get("role") == "tool":
            answered.add(message.get("tool_call_id", ""))
    return {called[i] for i in answered if i in called}, [name for i, name in called.items() if i not in answered], users


def read_gemini(body: dict) -> tuple[set[str], list[str], int]:
    calls: list[str] = []
    results: list[str] = []
    users = 0
    for content in body.get("contents", []):
        parts = content.get("parts", [])
        if content.get("role") == "user" and any("text" in part for part in parts):
            users += 1
        calls += [part["functionCall"]["name"] for part in parts if "functionCall" in part]
        results += [part["functionResponse"]["name"] for part in parts if "functionResponse" in part]
    unanswered = list(calls)
    for name in results:
        if name in unanswered:
            unanswered.remove(name)
    return set(results), unanswered, users


def serve(port_file: str, log_file: str) -> None:
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_):
            pass

        def reply(self, status: int, payload: dict):
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")
            gemini = ":generateContent" in self.path
            if not gemini and not self.path.endswith("/chat/completions"):
                return self.reply(404, {"error": {"message": f"the stand-in does not serve {self.path}"}})
            done, unanswered, users = read_gemini(body) if gemini else read_chat(body)
            step = next(((name, arguments) for name, arguments in PLAN if name not in done), None)
            record = {"protocol": "gemini" if gemini else "chat", "user_messages": users, "tools_with_results": sorted(done),
                      "unanswered_calls": unanswered, "answer": step[0] if step else "final text"}
            if unanswered and not gemini:
                record["answer"] = "HTTP 400"
            with lock, open(log_file, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(record) + "\n")
            if record["answer"] == "HTTP 400":
                return self.reply(400, {"error": {"type": "invalid_request_error", "message":
                                  "An assistant message with 'tool_calls' must be followed by tool messages responding to each 'tool_call_id'."}})
            call_id = "call_" + uuid.uuid4().hex[:12]
            if gemini:
                parts = [{"functionCall": {"id": call_id, "name": step[0], "args": step[1]}}] if step else [{"text": DONE}]
                return self.reply(200, {"candidates": [{"content": {"role": "model", "parts": parts}, "finishReason": "STOP", "index": 0}],
                                        "usageMetadata": {"promptTokenCount": 100, "candidatesTokenCount": 20, "totalTokenCount": 120}, "modelVersion": "stand-in"})
            message: dict = {"role": "assistant", "content": None if step else DONE}
            if step:
                message["tool_calls"] = [{"id": call_id, "type": "function", "function": {"name": step[0], "arguments": json.dumps(step[1])}}]
            self.reply(200, {"id": "chatcmpl-" + uuid.uuid4().hex[:8], "object": "chat.completion", "created": 0, "model": body.get("model", "stand-in"),
                             "choices": [{"index": 0, "message": message, "finish_reason": "tool_calls" if step else "stop"}],
                             "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    with open(port_file, "w", encoding="utf-8") as handle:
        handle.write(str(server.server_address[1]))
    server.serve_forever()


if __name__ == "__main__":
    serve(sys.argv[1], sys.argv[2])
