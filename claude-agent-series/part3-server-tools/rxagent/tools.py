"""Client tools (run in this process) and server tools (run by Anthropic) for the prescription assistant.

Client tools are unchanged from Part 1: strict JSON Schemas, a flag for state changes, and
handlers that run here, behind the approval gate when they change state.

Server tools are new in Part 3. Web search and web fetch run on Anthropic's side: Claude calls
them, the API executes them and returns the results in the same response. This process never
sees the call before it runs, so the controls that matter are the ones in the tool definition:
which domains, how many uses, where fetchable URLs may come from, and no code-execution caller.

Keep identifiers and clinical data out of the schemas themselves: strict tool schemas are
compiled and cached separately from message content.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from .rx_service import RxService

MAX_RESULT_CHARS = 8_000  # keep one tool result from flooding the context window

# Medicines regulators whose safety communications the assistant may read. Subdomains are included.
REGULATOR_DOMAINS: tuple[str, ...] = ("hpra.ie", "ema.europa.eu")


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


@dataclass(frozen=True)
class ServerToolPolicy:
    domains: tuple[str, ...] = REGULATOR_DOMAINS
    max_searches: int = 3       # per request; billed per search
    max_fetches: int = 2        # per request; billed as input tokens only
    fetch_max_tokens: int = 6_000


SERVER_TOOL_NAMES = frozenset({"web_search", "web_fetch"})


def server_tool_definitions(policy: ServerToolPolicy) -> list[dict[str, Any]]:
    """Web search and web fetch, locked to the regulators.

    allowed_callers=["direct"] keeps Claude from calling them from inside a code-execution
    container ("dynamic filtering"), which the documentation lists as not eligible for zero
    data retention or HIPAA. url_sources stops URLs that appear in client tool results (data
    from our own systems) from becoming fetchable; only the user's message and search results are.
    """
    domains = list(policy.domains)
    return [
        {
            "type": "web_search_20260318",
            "name": "web_search",
            "max_uses": policy.max_searches,
            "allowed_domains": domains,
            "allowed_callers": ["direct"],
            "user_location": {"type": "approximate", "country": "IE", "timezone": "Europe/Dublin"},
        },
        {
            "type": "web_fetch_20260318",
            "name": "web_fetch",
            "max_uses": policy.max_fetches,
            "allowed_domains": domains,
            "allowed_callers": ["direct"],
            "url_sources": {"user_input": {"type": "all"},
                            "client_tool_results": {"type": "none"},
                            "server_tool_results": {"type": "all"}},
            "citations": {"enabled": True},
            "max_content_tokens": policy.fetch_max_tokens,
        },
    ]


def definitions(policy: ServerToolPolicy | None = None) -> list[dict[str, Any]]:
    """Client tools first, server tools last; the order is stable so the cached prefix stays valid."""
    defs = [t.definition() for t in TOOLS]
    if policy is not None:
        defs += server_tool_definitions(policy)
    return defs


def to_result_text(value: Any) -> str:
    """Serialise a handler's return value for a tool_result block, with a size cap."""
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if len(text) > MAX_RESULT_CHARS:
        text = text[:MAX_RESULT_CHARS] + f'... [truncated: {len(text)} characters in full; ask for less]'
    return text
