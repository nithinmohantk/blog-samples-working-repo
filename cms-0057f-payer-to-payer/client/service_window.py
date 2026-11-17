"""The CMS-0057-F payer-to-payer window: data with a date of service within five years of the request.

Bulk Data `_since` filters on when the server last changed a resource (meta.lastUpdated), not on when the
care happened. A claim migrated into a new platform last month has a recent lastUpdated and a service
date from 2016. So the window has to be applied to a clinical or billing date, chosen per resource type.
The choice below is this sample's; a real payer should agree it with its compliance team and record it.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

# Resource type -> ordered list of paths whose first present value is the date of service.
SERVICE_DATE_PATHS: dict[str, list[tuple[str, ...]]] = {
    "ExplanationOfBenefit": [("billablePeriod", "end"), ("billablePeriod", "start"), ("created",)],
    "Encounter": [("period", "end"), ("period", "start")],
    "Condition": [("recordedDate",), ("onsetDateTime",)],
    "Observation": [("effectiveDateTime",), ("effectivePeriod", "end"), ("issued",)],
    "MedicationRequest": [("authoredOn",)],
    "Procedure": [("performedDateTime",), ("performedPeriod", "end")],
}
# Context resources that carry no date of service and are always sent with the member's data.
ALWAYS_INCLUDED = {"Patient", "Coverage", "Organization", "Practitioner"}


@dataclass(frozen=True)
class Decision:
    resource_type: str
    resource_id: str
    service_date: date | None
    keep: bool
    reason: str


def five_years_before(request_date: date) -> date:
    try:
        return request_date.replace(year=request_date.year - 5)
    except ValueError:                       # 29 February
        return request_date.replace(year=request_date.year - 5, day=28)


def service_date(resource: dict) -> date | None:
    for path in SERVICE_DATE_PATHS.get(resource["resourceType"], []):
        value = resource
        for step in path:
            value = value.get(step) if isinstance(value, dict) else None
        if isinstance(value, str) and len(value) >= 10:
            return date.fromisoformat(value[:10])
    return None


def decide(resource: dict, request_date: date) -> Decision:
    rtype, rid = resource["resourceType"], resource.get("id", "?")
    if rtype in ALWAYS_INCLUDED:
        return Decision(rtype, rid, None, True, "context resource")
    when = service_date(resource)
    if when is None:
        # No usable date: hold it back for review rather than send data outside the window.
        return Decision(rtype, rid, None, False, "no date of service; held for review")
    if when > request_date:
        return Decision(rtype, rid, when, False, "date of service after the request")
    if when < five_years_before(request_date):
        return Decision(rtype, rid, when, False, "older than five years")
    return Decision(rtype, rid, when, True, "within five years")


def apply_window(resources: dict[str, list[dict]], request_date: date) -> list[Decision]:
    return [decide(r, request_date) for items in resources.values() for r in items]
