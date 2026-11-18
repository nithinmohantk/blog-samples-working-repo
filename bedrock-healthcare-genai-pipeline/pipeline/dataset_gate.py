"""Gate for supervised fine-tuning data before it leaves the EU.

Bedrock model customisation for Nova runs in US Regions, so the training set
crosses a border. The gate enforces the rule that makes that acceptable: the
set contains no personal data. Every record must declare where it came from,
must be in the Bedrock conversation format, and must contain no identifier.

The gate writes a certificate. The pipeline refuses to start a customisation
job without one whose hash matches the file being submitted.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .identifiers import scan

SCHEMA_VERSION = "bedrock-conversation-2024"
ALLOWED_PROVENANCE = {"synthetic", "hiqa-published", "hse-published", "author-written"}


@dataclass
class Problem:
    line: int
    code: str
    detail: str


@dataclass
class GateResult:
    path: str
    sha256: str
    records: int
    problems: list[Problem] = field(default_factory=list)
    provenance: dict[str, int] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return not self.problems

    def certificate(self) -> dict:
        if not self.passed:
            raise ValueError("no certificate for a dataset that failed the gate")
        return {
            "dataset_sha256": self.sha256,
            "records": self.records,
            "provenance": self.provenance,
            "personal_data": False,
            "gate": "dataset_gate/1",
        }


def _texts(record: dict) -> list[str]:
    out = [block.get("text", "") for block in record.get("system", [])]
    for message in record.get("messages", []):
        out.extend(block.get("text", "") for block in message.get("content", []))
    return out


def check_record(record: dict, line: int) -> list[Problem]:
    problems: list[Problem] = []
    if record.get("schemaVersion") != SCHEMA_VERSION:
        problems.append(Problem(line, "SCHEMA", f"schemaVersion must be {SCHEMA_VERSION}"))
    messages = record.get("messages")
    if not isinstance(messages, list) or len(messages) < 2:
        problems.append(Problem(line, "SHAPE", "messages needs at least one user and one assistant turn"))
        return problems
    for i, message in enumerate(messages):
        expected = "user" if i % 2 == 0 else "assistant"
        if message.get("role") != expected:
            problems.append(Problem(line, "ROLES", f"message {i} should be {expected}"))
        content = message.get("content")
        if not isinstance(content, list) or not all(isinstance(b, dict) and b.get("text") for b in content):
            problems.append(Problem(line, "CONTENT", f"message {i} needs text content blocks"))
    if messages[-1].get("role") != "assistant":
        problems.append(Problem(line, "ROLES", "last message must be the assistant answer"))

    provenance = record.get("metadata", {}).get("provenance")
    if provenance not in ALLOWED_PROVENANCE:
        problems.append(Problem(line, "PROVENANCE", f"provenance {provenance!r} is not an allowed source"))

    for text in _texts(record):
        for finding in scan(text):
            problems.append(Problem(line, "IDENTIFIER", finding.masked(text)))
    return problems


def strip_metadata(record: dict) -> dict:
    """The submitted file carries only fields Bedrock reads."""
    return {k: v for k, v in record.items() if k in ("schemaVersion", "system", "messages")}


def run_gate(source: Path, submit_path: Path, min_records: int = 100) -> GateResult:
    """Check `source`, and if it passes write the Bedrock-ready file to `submit_path`."""
    problems: list[Problem] = []
    provenance: dict[str, int] = {}
    cleaned: list[str] = []
    with source.open(encoding="utf-8") as handle:
        for number, raw in enumerate(handle, start=1):
            if not raw.strip():
                problems.append(Problem(number, "BLANK", "blank line in JSONL"))
                continue
            try:
                record = json.loads(raw)
            except json.JSONDecodeError as exc:
                problems.append(Problem(number, "JSON", str(exc)))
                continue
            problems.extend(check_record(record, number))
            tag = record.get("metadata", {}).get("provenance", "missing")
            provenance[tag] = provenance.get(tag, 0) + 1
            cleaned.append(json.dumps(strip_metadata(record), ensure_ascii=False, separators=(",", ":")))

    if len(cleaned) < min_records:
        problems.append(Problem(0, "SIZE", f"{len(cleaned)} records, at least {min_records} required"))

    body = ("\n".join(cleaned) + "\n").encode("utf-8")
    result = GateResult(str(submit_path), hashlib.sha256(body).hexdigest(), len(cleaned), problems, provenance)
    if result.passed:
        submit_path.write_bytes(body)
    return result


def report(result: GateResult) -> str:
    return json.dumps({**asdict(result), "passed": result.passed}, indent=2)
