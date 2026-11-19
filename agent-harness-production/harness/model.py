"""The model, as the harness sees it: messages in, one assistant message out.

Messages are plain dicts in the common chat shape. An assistant message may carry
``tool_calls``: a list of ``{"id", "name", "arguments"}`` where arguments is a JSON string,
because that is what model APIs return and it is not always valid JSON.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, Protocol

Message = dict[str, Any]


class Model(Protocol):
    name: str

    def complete(self, messages: list[Message], tools: list[dict[str, Any]]) -> Message: ...


class ScriptedModel:
    """A stand-in that answers from a function of the conversation, so runs repeat exactly."""

    def __init__(self, script: Callable[[list[Message]], Message], name: str = "scripted-1", cap: int = 500) -> None:
        self.name = name
        self.calls = 0
        self.largest_request_chars = 0
        self._script = script
        self._cap = cap

    def complete(self, messages: list[Message], tools: list[dict[str, Any]]) -> Message:
        self.calls += 1
        self.largest_request_chars = max(self.largest_request_chars, sum(len(str(m.get("content") or "")) for m in messages))
        if self.calls > self._cap:
            raise RuntimeError(f"lab cap: the model was called more than {self._cap} times")
        return self._script(messages)


def say(text: str) -> Message:
    return {"role": "assistant", "content": text}


def call(name: str, arguments: dict[str, Any] | str, call_id: str = "") -> Message:
    raw = arguments if isinstance(arguments, str) else json.dumps(arguments)
    return {"role": "assistant", "content": "", "tool_calls": [{"id": call_id or f"call-{name}", "name": name, "arguments": raw}]}


def last_tool_result(messages: list[Message]) -> str:
    for message in reversed(messages):
        if message["role"] == "tool":
            return str(message["content"])
    return ""


def tool_results(messages: list[Message]) -> int:
    return sum(1 for message in messages if message["role"] == "tool")
