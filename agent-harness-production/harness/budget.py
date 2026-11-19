"""Limits on one run. Every number is a decision somebody should make on purpose."""
from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class Budget:
    max_model_calls: int = 12
    max_tool_calls: int = 20
    max_seconds: float = 60.0
    max_result_chars: int = 4_000
    max_context_chars: int = 40_000

    model_calls: int = 0
    tool_calls: int = 0
    started: float = field(default_factory=time.monotonic)

    def exhausted(self) -> str | None:
        """The limit that was reached, or None while there is room."""
        if self.model_calls >= self.max_model_calls:
            return f"model calls ({self.max_model_calls})"
        if self.tool_calls >= self.max_tool_calls:
            return f"tool calls ({self.max_tool_calls})"
        if time.monotonic() - self.started >= self.max_seconds:
            return f"time ({self.max_seconds:g} s)"
        return None
