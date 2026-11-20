"""Tool definitions and handlers for the prescription assistant.

Each tool has a JSON Schema with `strict: true`, so Claude's inputs always match
the schema, and a flag saying whether it changes state. State-changing tools go
through the approval gate in loop.py; read-only tools can run in parallel.

Keep identifiers and clinical data out of the schemas themselves: strict tool
schemas are compiled and cached separately from message content.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from .rx_service import RxService

MAX_RESULT_CHARS = 8_000  # keep one tool result from flooding the context window


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    schema: dict[str, Any]
    handler: Callable[[RxService, dict[str, Any]], Any]
    changes_state: bool = False

    def definition(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description, "strict": True, "input_schema": self.schema}


def _object(properties: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


TOOLS: list[Tool] = [
    Tool(
        name="find_prescriptions",
        description="List every prescription for one patient, with status and medication. "
                    "Use this first when the user names a patient but not a prescription.",
        schema=_object({"patient_id": {"type": "string", "description": "Patient identifier, for example P-001"}}),
        handler=lambda svc, a: svc.find_for_patient(a["patient_id"]),
    ),
    Tool(
        name="get_prescription",
        description="Get one prescription by its identifier: medication, dose, status, prescriber, repeats.",
        schema=_object({"rx_id": {"type": "string", "description": "Prescription identifier, for example RX-1002"}}),
        handler=lambda svc, a: svc.get(a["rx_id"]),
    ),
    Tool(
        name="get_dispense_events",
        description="List when and where a prescription was dispensed, newest last. "
                    "An empty list means it has not been dispensed.",
        schema=_object({"rx_id": {"type": "string", "description": "Prescription identifier, for example RX-1002"}}),
        handler=lambda svc, a: svc.dispense_events(a["rx_id"]),
    ),
    Tool(
        name="cancel_prescription",
        description="Cancel an active prescription. This changes the record and needs a person's approval; "
                    "the result says whether it was approved. Give the clinical or administrative reason.",
        schema=_object({
            "rx_id": {"type": "string", "description": "Prescription identifier, for example RX-1003"},
            "reason": {"type": "string", "description": "Why the prescription is being cancelled, in one sentence"},
        }),
        handler=lambda svc, a: svc.cancel(a["rx_id"], a["reason"]),
        changes_state=True,
    ),
]

BY_NAME: dict[str, Tool] = {t.name: t for t in TOOLS}


def definitions() -> list[dict[str, Any]]:
    return [t.definition() for t in TOOLS]


def to_result_text(value: Any) -> str:
    """Serialise a handler's return value for a tool_result block, with a size cap."""
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if len(text) > MAX_RESULT_CHARS:
        text = text[:MAX_RESULT_CHARS] + f'... [truncated: {len(text)} characters in full; ask for less]'
    return text
