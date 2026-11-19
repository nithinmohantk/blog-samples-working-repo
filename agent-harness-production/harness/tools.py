"""Tools and their contracts."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from jsonschema import Draft202012Validator


class TransientError(Exception):
    """A failure worth trying again: a timeout downstream, a dropped connection."""


@dataclass(frozen=True)
class Call:
    """What a tool is told about the call it is serving."""

    run_id: str
    call_id: str

    @property
    def idempotency_key(self) -> str:
        return f"{self.run_id}:{self.call_id}"


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    run: Callable[[dict[str, Any], Call], Any]
    effect: Literal["read", "write"] = "read"
    timeout_s: float = 5.0
    attempts: int = 1


class Registry:
    def __init__(self, tools: list[Tool]) -> None:
        for tool in tools:
            Draft202012Validator.check_schema(tool.parameters)
        self._tools = {tool.name: tool for tool in tools}
        self._validators = {tool.name: Draft202012Validator(tool.parameters) for tool in tools}

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return sorted(self._tools)

    def describe(self) -> list[dict[str, Any]]:
        """The tool list in the shape model APIs take."""
        return [{"name": t.name, "description": t.description, "parameters": t.parameters} for t in self._tools.values()]

    def problems(self, name: str, arguments: dict[str, Any]) -> list[str]:
        """Why these arguments do not fit the tool's schema. Empty when they do."""
        errors = sorted(self._validators[name].iter_errors(arguments), key=lambda e: list(e.path))
        return [f"{'/'.join(str(p) for p in e.path) or '(arguments)'}: {e.message}" for e in errors]
