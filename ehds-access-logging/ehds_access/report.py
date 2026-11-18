"""Article 8f: tell the person who accessed their data, when, and which data.

The provisional agreement says the information is given without delay and free of charge, kept available
for at least three years after each access, and covers at least the healthcare provider or other
individuals who accessed the data, the date and time, and the data accessed. Member States may restrict
the right in exceptional circumstances, which is why naming the individual is a setting here.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from .audit import ACT_REASON, CATEGORY_DETAIL



@dataclass(frozen=True)
class AccessRow:
    when: str
    provider: str
    individual: str | None
    categories: tuple[str, ...]
    emergency: bool


def _agents(event: dict) -> tuple[str, str]:
    people = [a["who"].get("display", a["who"].get("reference")) for a in event.get("agent", [])
              if a["who"].get("reference", "").startswith("Practitioner/")]
    orgs = [a["who"].get("display", a["who"].get("reference")) for a in event.get("agent", [])
            if a["who"].get("reference", "").startswith("Organization/")]
    return (orgs[0] if orgs else "unknown provider"), (people[0] if people else "")


def rows(events: list[dict], *, show_individual: bool = True) -> list[AccessRow]:
    out = []
    for e in events:
        provider, person = _agents(e)
        cats = sorted({d["valueString"] for ent in e.get("entity", []) for d in ent.get("detail", [])
                       if d.get("type") == CATEGORY_DETAIL})
        emergency = any(c.get("system") == ACT_REASON and c.get("code") == "ETREAT"
                        for p in e.get("purposeOfEvent", []) for c in p.get("coding", []))
        out.append(AccessRow(e["recorded"], provider, person if show_individual else None, tuple(cats), emergency))
    return sorted(out, key=lambda r: r.when, reverse=True)


def render(report: list[AccessRow]) -> str:
    lines = [f"{'When (UTC)':<24} {'Provider':<26} {'Who':<18} Data"]
    for r in report:
        flag = "  EMERGENCY ACCESS" if r.emergency else ""
        lines.append(f"{r.when[:19].replace('T', ' '):<24} {r.provider:<26} {(r.individual or '-'):<18} "
                     f"{', '.join(r.categories) or '(nothing shown)'}{flag}")
    return "\n".join(lines)


def keep_until(recorded: datetime, years: int = 3) -> datetime:
    """'At least three years after each data access'. An access on 29 February is kept until 1 March."""
    try:
        return recorded.replace(year=recorded.year + years)
    except ValueError:
        return recorded.replace(year=recorded.year + years, month=3, day=1)


def may_delete(event: dict, now: datetime | None = None) -> bool:
    """True only after the three-year minimum. A longer national retention period still applies."""
    recorded = datetime.fromisoformat(event["recorded"].replace("Z", "+00:00"))
    return (now or datetime.now(timezone.utc)) >= keep_until(recorded)
