"""The audit back end: read-only prescription data plus an append-only findings register.

Progress lives here, not in the conversation. That is what lets the agent survive a
compaction or a restart: whatever the model has forgotten, get_progress can tell it.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

from .data import RULES, generate

PAGE_SIZE = 8
MAX_DETAILS = 4


class AuditError(Exception):
    """A problem the agent can fix by calling the tool differently."""


@dataclass
class AuditService:
    prescriptions: dict[str, dict]
    dispenses: dict[str, list[dict]]
    findings: dict[tuple[str, str], str] = field(default_factory=dict)   # (rx_id, rule) -> note
    reviewed: set[str] = field(default_factory=set)

    @classmethod
    def with_sample_data(cls) -> "AuditService":
        rx, d = generate()
        return cls(rx, d)

    # ---- reads -------------------------------------------------------------------
    def list_page(self, page: int) -> dict[str, Any]:
        ids = sorted(self.prescriptions)
        pages = (len(ids) + PAGE_SIZE - 1) // PAGE_SIZE
        if not 1 <= page <= pages:
            raise AuditError(f"Page {page} does not exist; pages run from 1 to {pages}.")
        chunk = ids[(page - 1) * PAGE_SIZE: page * PAGE_SIZE]
        return {"page": page, "pages": pages,
                "prescriptions": [{k: self.prescriptions[i][k] for k in ("id", "patient", "medication", "status")}
                                  for i in chunk]}

    def details(self, rx_ids: list[str]) -> list[dict]:
        if not rx_ids or len(rx_ids) > MAX_DETAILS:
            raise AuditError(f"Ask for between 1 and {MAX_DETAILS} prescriptions at a time.")
        missing = [i for i in rx_ids if i not in self.prescriptions]
        if missing:
            raise AuditError(f"Unknown prescription identifiers: {', '.join(missing)}.")
        return [{**copy.deepcopy(self.prescriptions[i]), "dispenses": copy.deepcopy(self.dispenses.get(i, []))}
                for i in rx_ids]

    def progress(self) -> dict[str, Any]:
        ids = sorted(self.prescriptions)
        left = [i for i in ids if i not in self.reviewed]
        return {"total": len(ids), "reviewed": len(self.reviewed), "findings_recorded": len(self.findings),
                "next_unreviewed": left[:PAGE_SIZE], "remaining": len(left)}

    # ---- writes (append-only, idempotent) -------------------------------------------
    def record(self, items: list[dict[str, str]]) -> dict[str, Any]:
        added, already = 0, 0
        for it in items:
            rid, rule = it["rx_id"], it["rule"]
            if rid not in self.prescriptions:
                raise AuditError(f"Unknown prescription identifier {rid}; nothing in this batch was recorded.")
            if rule not in RULES:
                raise AuditError(f"Unknown rule {rule}; use one of {', '.join(RULES)}.")
        for it in items:
            key = (it["rx_id"], it["rule"])
            if key in self.findings:
                already += 1
            else:
                self.findings[key] = it.get("note", "")
                added += 1
        return {"added": added, "already_recorded": already, "findings_recorded": len(self.findings)}

    def mark_reviewed(self, rx_ids: list[str]) -> dict[str, Any]:
        missing = [i for i in rx_ids if i not in self.prescriptions]
        if missing:
            raise AuditError(f"Unknown prescription identifiers: {', '.join(missing)}.")
        self.reviewed.update(rx_ids)
        return self.progress()

    # ---- checkpointing -------------------------------------------------------------
    def to_state(self) -> dict[str, Any]:
        return {"findings": [[r, rule, note] for (r, rule), note in sorted(self.findings.items())],
                "reviewed": sorted(self.reviewed)}

    def load_state(self, state: dict[str, Any]) -> None:
        self.findings = {(r, rule): note for r, rule, note in state["findings"]}
        self.reviewed = set(state["reviewed"])
