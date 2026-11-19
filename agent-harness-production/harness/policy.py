"""Who decides whether a tool call goes ahead."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .tools import Tool

Approver = Callable[[Tool, dict[str, Any]], bool]


def nobody(tool: Tool, arguments: dict[str, Any]) -> bool:
    """The default approver: there is no one to ask, so the answer is no."""
    return False


@dataclass(frozen=True)
class Policy:
    """Reads run. Writes run only if the approver says yes. The approver is code you own, not the model."""

    approve: Approver = nobody

    def refusal(self, tool: Tool, arguments: dict[str, Any]) -> str | None:
        if tool.effect == "read":
            return None
        return None if self.approve(tool, arguments) else f"'{tool.name}' changes something and was not approved"
