"""Tool definitions for the audit agent: strict schemas, batch-friendly, idempotent writes."""
from __future__ import annotations

import json
from typing import Any, Callable

from .data import RULES
from .service import AuditService

Handler = Callable[[AuditService, dict[str, Any]], Any]


def _obj(props: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


_ID_LIST = {"type": "array", "items": {"type": "string"}, "description": "Prescription identifiers, for example RX-2001"}

TOOLS: list[tuple[dict[str, Any], Handler]] = [
    ({"name": "get_progress", "strict": True,
      "description": "How far the audit has got: totals, findings recorded, and the next unreviewed prescriptions. "
                     "Call this first, and again whenever you are unsure what is left.",
      "input_schema": _obj({})},
     lambda s, a: s.progress()),
    ({"name": "list_prescriptions", "strict": True,
      "description": "One page (8 prescriptions) of the audit list: id, patient, medication, status.",
      "input_schema": _obj({"page": {"type": "integer", "description": "Page number, starting at 1"}})},
     lambda s, a: s.list_page(a["page"])),
    ({"name": "get_details", "strict": True,
      "description": "Full records for up to 4 prescriptions: issued date, repeats remaining and dispense history.",
      "input_schema": _obj({"rx_ids": _ID_LIST})},
     lambda s, a: s.details(a["rx_ids"])),
    ({"name": "record_findings", "strict": True,
      "description": "Record audit findings in the register. Recording the same prescription and rule twice is harmless.",
      "input_schema": _obj({"findings": {"type": "array", "items": _obj({
          "rx_id": {"type": "string"},
          "rule": {"type": "string", "enum": list(RULES)},
          "note": {"type": "string", "description": "One short sentence with the dates or counts that triggered the rule"},
      })}})},
     lambda s, a: s.record(a["findings"])),
    ({"name": "mark_reviewed", "strict": True,
      "description": "Mark prescriptions as reviewed once every rule has been checked for them, findings or not.",
      "input_schema": _obj({"rx_ids": _ID_LIST})},
     lambda s, a: s.mark_reviewed(a["rx_ids"])),
]

DEFINITIONS = [d for d, _ in TOOLS]
HANDLERS: dict[str, Handler] = {d["name"]: h for d, h in TOOLS}


def to_result_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
