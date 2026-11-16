"""The authorization decision for one tool call. Pure functions: no network, no framework."""
from __future__ import annotations

from dataclasses import dataclass

from smart.scopes import Grant, allowed_values, matching

CATEGORY_SYSTEM = "http://terminology.hl7.org/CodeSystem/observation-category"


@dataclass(frozen=True)
class Need:
    """What a tool needs from the token."""

    resource: str
    permission: str  # one of c, r, u, d, s
    across_patients: bool = False  # true for tools that are not about one patient


NEEDS = {
    "get_patient": Need("Patient", "r"),
    "search_patients": Need("Patient", "s", across_patients=True),
    "list_observations": Need("Observation", "s"),
    "get_observation": Need("Observation", "r"),
    "list_medications": Need("MedicationRequest", "s"),
    "list_conditions": Need("Condition", "s"),
    "record_observation": Need("Observation", "c"),
}


class Denied(Exception):
    """The call is refused. `kind` and `reason` go to the audit log, never to the caller."""

    def __init__(self, kind: str, reason: str) -> None:
        super().__init__("DENIED: this token does not permit that request")
        self.kind, self.reason = kind, reason


@dataclass(frozen=True)
class Decision:
    patient: str | None  # the one patient this call may touch; None only for across-patient tools
    categories: set[str] | None  # observation categories the call is limited to; None for no limit


def usable(grants: list[Grant], need: Need) -> list[Grant]:
    """The grants that can satisfy a tool. A patient-level grant never satisfies an across-patient tool."""
    found = matching(grants, need.resource, need.permission)
    return [grant for grant in found if grant.context != "patient"] if need.across_patients else found


def visible(grants: list[Grant]) -> list[str]:
    """The tools worth showing to this token. A convenience for the model, not a control."""
    return [tool for tool, need in NEEDS.items() if usable(grants, need)]


def decide(grants: list[Grant], token_patient: str | None, tool: str, patient_id: str | None = None, category: str | None = None) -> Decision:
    need = NEEDS[tool]
    found = usable(grants, need)
    if not found:
        raise Denied("scope", f"no scope grants {need.resource}.{need.permission}")
    wide = [grant for grant in found if grant.context in ("user", "system")]
    if need.across_patients:
        return Decision(None, None)
    if wide:
        if not patient_id:
            raise Denied("context", "a user-level token must name the patient")
        patient, chosen = patient_id, wide
    else:
        if not token_patient:
            raise Denied("context", "patient-level scope without a patient in the token")
        if patient_id and patient_id != token_patient:
            raise Denied("compartment", f"asked for Patient/{patient_id}, token is for Patient/{token_patient}")
        patient, chosen = token_patient, found
    categories = allowed_values(chosen, "category") if need.resource == "Observation" else None
    if categories is not None:
        categories = {value.removeprefix(CATEGORY_SYSTEM + "|") for value in categories}
        if category and category not in categories:
            raise Denied("filter", f"category {category} is outside the granted {sorted(categories)}")
    return Decision(patient, categories)


def in_scope(resource: dict, decision: Decision) -> bool:
    """Check a resource that came back from the FHIR server against the decision. The last line of defence."""
    if decision.patient is not None:
        if resource["resourceType"] == "Patient":
            if resource.get("id") != decision.patient:
                return False
        elif (resource.get("subject") or resource.get("patient") or {}).get("reference") != f"Patient/{decision.patient}":
            return False
    if decision.categories is not None and resource["resourceType"] == "Observation":
        held = {coding.get("code") for concept in resource.get("category", []) for coding in concept.get("coding", []) if coding.get("system") == CATEGORY_SYSTEM}
        if not held & decision.categories:
            return False
    return True
