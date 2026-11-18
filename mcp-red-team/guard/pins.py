"""Pin what was approved. A tool is approved as an exact definition, not as a name.

The fingerprint covers everything a model or a client acts on: name, description, both schemas and
the annotations. If any of it changes, the pin no longer matches and the tool is held until a person
approves the new definition. This is the control against a server that changes its tools after approval.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass, field
from typing import Any

FIELDS = ("name", "description", "inputSchema", "outputSchema", "annotations")


def fingerprint(tool: dict[str, Any]) -> str:
    material = {key: tool.get(key) for key in FIELDS}
    return hashlib.sha256(json.dumps(material, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


@dataclass
class Verdict:
    unchanged: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    unapproved: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not (self.changed or self.unapproved)


class PinStore:
    """Approved fingerprints per server, kept in one JSON file that belongs in version control or a managed profile."""

    def __init__(self, path: str) -> None:
        self.path = path
        self.pins: dict[str, dict[str, str]] = {}
        if os.path.exists(path):
            with open(path, encoding="utf-8") as handle:
                self.pins = json.load(handle)

    def approve(self, server: str, tools: list[dict[str, Any]]) -> None:
        self.pins[server] = {tool["name"]: fingerprint(tool) for tool in tools}
        directory = os.path.dirname(os.path.abspath(self.path))
        with tempfile.NamedTemporaryFile("w", dir=directory, delete=False, encoding="utf-8") as handle:
            json.dump(self.pins, handle, indent=2, sort_keys=True)
        os.replace(handle.name, self.path)  # a half-written pin file must never be read as "nothing approved"

    def verify(self, server: str, tools: list[dict[str, Any]]) -> Verdict:
        approved, verdict = self.pins.get(server, {}), Verdict()
        for tool in tools:
            name = tool["name"]
            if name not in approved:
                verdict.unapproved.append(name)
            elif approved[name] != fingerprint(tool):
                verdict.changed.append(name)
            else:
                verdict.unchanged.append(name)
        verdict.missing = sorted(set(approved) - {tool["name"] for tool in tools})
        return verdict
