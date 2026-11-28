"""Finding model shared by every check."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import IntEnum


class Severity(IntEnum):
    """Ordered so that a threshold comparison is a plain integer comparison."""

    INFO = 10
    WARN = 20
    ACTION = 30

    @classmethod
    def parse(cls, value: str) -> "Severity":
        try:
            return cls[value.strip().upper()]
        except KeyError as exc:
            allowed = ", ".join(s.name.lower() for s in cls)
            raise ValueError(f"unknown severity {value!r}; use one of: {allowed}") from exc


@dataclass(frozen=True, slots=True)
class Finding:
    check: str
    severity: Severity
    path: str
    subject: str
    message: str
    action: str
    reference: str

    def to_dict(self) -> dict[str, str]:
        data = asdict(self)
        data["severity"] = self.severity.name
        return data
