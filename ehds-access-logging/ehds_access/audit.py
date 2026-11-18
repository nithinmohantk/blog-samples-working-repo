"""The logging part: one FHIR R4 AuditEvent per access, carrying what Annex II point 3.4 asks for.

Annex II 3.4 (provisional agreement, March 2024): for each access event or group of events, log at least
  (a) the healthcare provider or other individuals who accessed the data,
  (b) the specific individual(s) who accessed the data,
  (c) the categories of data accessed,
  (d) the time and date of access,
  (e) the origin(s) of the data.
Article 7a(3) adds that access to restricted data in a vital-interest emergency must be logged in a
clear format the person can easily read; that is the purposeOfEvent ETREAT below.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from .categories import category_of

DCM = "http://dicom.nema.org/resources/ontology/DCM"
RESTFUL = "http://hl7.org/fhir/restful-interaction"
ENTITY_TYPE = "http://terminology.hl7.org/CodeSystem/audit-entity-type"
OBJECT_ROLE = "http://terminology.hl7.org/CodeSystem/object-role"
ACT_REASON = "http://terminology.hl7.org/CodeSystem/v3-ActReason"
CATEGORY_DETAIL = "ehds-category"
ORIGIN_DETAIL = "ehds-origin"


@dataclass(frozen=True)
class Requester:
    practitioner: str        # Practitioner/... : Annex II 3.4(b)
    practitioner_name: str
    organization: str        # Organization/... : Annex II 3.4(a)
    organization_name: str


def origin_of(resource: dict) -> str:
    """Annex II 3.4(e). Where the data came from: the recording organisation, or the meta.source system."""
    for key in ("performer", "author", "requester", "custodian"):
        refs = resource.get(key)
        refs = refs if isinstance(refs, list) else [refs] if refs else []
        for ref in refs:
            ref = ref.get("actor", ref) if isinstance(ref, dict) else {}
            if ref.get("reference", "").startswith("Organization/"):
                return ref["reference"]
    return resource.get("meta", {}).get("source", "unknown")


def access_event(requester: Requester, patient: str, returned: list[dict], *, interaction: str,
                 emergency: bool = False, observer: str = "Device/ehr-system",
                 when: datetime | None = None) -> dict:
    """The AuditEvent for one request. `returned` is what the user actually saw, after any restriction."""
    recorded = (when or datetime.now(timezone.utc)).isoformat(timespec="milliseconds")
    entities = [{"what": {"reference": patient},
                 "type": {"system": ENTITY_TYPE, "code": "1", "display": "Person"},
                 "role": {"system": OBJECT_ROLE, "code": "1", "display": "Patient"}}]
    for resource in returned:
        category = category_of(resource)
        entities.append({
            "what": {"reference": f"{resource['resourceType']}/{resource['id']}"},
            "type": {"system": ENTITY_TYPE, "code": "2", "display": "System Object"},
            "role": {"system": OBJECT_ROLE, "code": "4", "display": "Domain Resource"},
            "detail": [{"type": CATEGORY_DETAIL, "valueString": category or "other"},
                       {"type": ORIGIN_DETAIL, "valueString": origin_of(resource)}],
        })
    reason = ("ETREAT", "Emergency Treatment") if emergency else ("TREAT", "treatment")
    return {
        "resourceType": "AuditEvent",
        "type": {"system": DCM, "code": "110110", "display": "Patient Record"},
        "subtype": [{"system": RESTFUL, "code": interaction}],
        "action": "R" if interaction == "read" else "E",
        "recorded": recorded,
        "outcome": "0",
        "purposeOfEvent": [{"coding": [{"system": ACT_REASON, "code": reason[0], "display": reason[1]}]}],
        "agent": [
            {"who": {"reference": requester.practitioner, "display": requester.practitioner_name},
             "requestor": True},
            {"who": {"reference": requester.organization, "display": requester.organization_name},
             "requestor": False},
        ],
        "source": {"observer": {"reference": observer}},
        "entity": entities,
    }
