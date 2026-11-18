"""Article 8e: the person restricts access to all or part of their data.

Two rules in the text shape the code:
  * Article 8e: "The fact that a restriction has been made by the natural person shall not be visible
    to healthcare providers." So the filtered result must look like a complete one, including its count.
  * Article 7a(3): where access is necessary to protect the vital interests of the person, a provider may
    access restricted data, and that access is logged (see audit.py, purposeOfEvent ETREAT).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .categories import category_of


@dataclass(frozen=True)
class Restriction:
    patient: str                                          # Patient/...
    categories: frozenset[str]                            # Article 5 categories the person has restricted
    except_providers: frozenset[str] = field(default_factory=frozenset)  # Organization/... still allowed


def visible(resources: list[dict], restriction: Restriction | None, organization: str,
            *, emergency: bool = False) -> list[dict]:
    if restriction is None or emergency or organization in restriction.except_providers:
        return list(resources)
    return [r for r in resources if category_of(r) not in restriction.categories]


def searchset(resources: list[dict]) -> dict:
    """A Bundle built from the filtered list only. Passing on the server's total would count hidden items."""
    return {"resourceType": "Bundle", "type": "searchset", "total": len(resources),
            "entry": [{"fullUrl": f"{r['resourceType']}/{r['id']}", "resource": r,
                       "search": {"mode": "match"}} for r in resources]}
