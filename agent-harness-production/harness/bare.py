"""The loop most agents start as. It works in a demo. The lab shows what it does on a bad day."""
from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from .model import Message, Model


def run_bare(model: Model, tools: dict[str, Callable[..., Any]], task: str) -> str:
    messages: list[Message] = [{"role": "user", "content": task}]
    while True:
        reply = model.complete(messages, [])
        messages.append(reply)
        if not reply.get("tool_calls"):
            return str(reply["content"])
        for call in reply["tool_calls"]:
            result = tools[call["name"]](**json.loads(call["arguments"]))
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": str(result)})
