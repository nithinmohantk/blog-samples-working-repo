"""An MCP server in front of a FHIR R4 server. What a caller may do is decided by the SMART scopes in its token.

Synthetic data only. Not clinically validated, and not a medical device.
"""
from __future__ import annotations

import json
import os
import re
import time
from typing import Any

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from mcp.types import Tool, ToolAnnotations

from server.fhir import Fhir
from server.policy import CATEGORY_SYSTEM, Decision, Denied, decide, in_scope, visible
from server.tokens import JwtVerifier, SmartToken
from smart.scopes import parse

ISSUER = os.environ["MCP_ISSUER"]
AUDIENCE = os.environ["MCP_AUDIENCE"]  # this server's own URL: a token minted for anything else is refused
AUDIT_LOG = os.environ.get("MCP_AUDIT_LOG", "audit.jsonl")
IDENTIFIER = re.compile(r"[A-Za-z0-9\-.]{1,64}")  # the FHIR id type
CATEGORIES = ("laboratory", "vital-signs")
READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=False)

fhir = Fhir(os.environ["FHIR_BASE"])
with open(os.environ["MCP_PUBLIC_KEY_FILE"], encoding="utf-8") as handle:
    verifier = JwtVerifier(handle.read(), ISSUER, AUDIENCE)


class ScopedMCP(FastMCP):
    """Lists only the tools the caller's scopes can use. Every call is still checked: see authorize()."""

    async def list_tools(self) -> list[Tool]:
        token = get_access_token()
        shown = set(visible(parse(token.scopes))) if token else set()
        return [tool for tool in await super().list_tools() if tool.name in shown]


mcp = ScopedMCP(
    "fhir",
    port=int(os.environ.get("MCP_PORT", "8000")),
    stateless_http=True,
    json_response=True,
    token_verifier=verifier,
    auth=AuthSettings(issuer_url=ISSUER, resource_server_url=AUDIENCE),
)


def audit(token: SmartToken | None, tool: str, outcome: str, patient: str | None, detail: str = "") -> None:
    """One line per call, allowed or refused. Identifiers only: no token and no clinical content."""
    entry = {"time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "subject": token.subject if token else None, "client": token.client_id if token else None, "tool": tool, "patient": patient, "outcome": outcome, "detail": detail}
    with open(AUDIT_LOG, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\n")


def authorize(tool: str, patient_id: str | None = None, category: str | None = None) -> tuple[SmartToken, Decision]:
    """Called first by every tool. Raises Denied, which the caller sees as one fixed sentence."""
    token = get_access_token()
    if not isinstance(token, SmartToken):
        raise Denied("token", "no verified token")
    try:
        if patient_id is not None and not IDENTIFIER.fullmatch(patient_id):
            raise Denied("input", "patient_id is not a FHIR id")
        if category is not None and category not in CATEGORIES:
            raise Denied("input", "unknown category")
        decision = decide(parse(token.scopes), token.patient, tool, patient_id, category)
    except Denied as denied:
        audit(token, tool, f"denied:{denied.kind}", token.patient, denied.reason)
        raise
    audit(token, tool, "allowed", decision.patient)
    return token, decision


def observation_summary(resource: dict) -> dict:
    quantity = resource.get("valueQuantity", {})
    return {
        "id": resource.get("id"),
        "code": (resource.get("code", {}).get("coding") or [{}])[0].get("code"),
        "display": resource.get("code", {}).get("text"),
        "value": quantity.get("value"),
        "unit": quantity.get("unit"),
        "effective": resource.get("effectiveDateTime"),
        "category": [coding.get("code") for concept in resource.get("category", []) for coding in concept.get("coding", [])],
    }


@mcp.tool(annotations=READ_ONLY)
async def get_patient(patient_id: str | None = None) -> dict:
    """Name, birth date and gender of one patient. Leave patient_id out to mean the patient this session is about."""
    _, decision = authorize("get_patient", patient_id)
    resource = await fhir.read("Patient", decision.patient)
    if resource is None or not in_scope(resource, decision):
        return {"found": False}
    name = (resource.get("name") or [{}])[0]
    return {"found": True, "id": resource["id"], "name": " ".join(name.get("given", []) + [name.get("family", "")]).strip(), "birth_date": resource.get("birthDate"), "gender": resource.get("gender")}


@mcp.tool(annotations=READ_ONLY)
async def search_patients(family_name: str) -> list[dict]:
    """Find patients by family name. For clinician sessions only."""
    authorize("search_patients")
    found = await fhir.search("Patient", {"family": family_name})
    return [{"id": resource["id"], "family": (resource.get("name") or [{}])[0].get("family"), "birth_date": resource.get("birthDate")} for resource in found]


@mcp.tool(annotations=READ_ONLY)
async def list_observations(category: str | None = None, code: str | None = None, patient_id: str | None = None) -> list[dict]:
    """Observations for one patient, newest first. category is laboratory or vital-signs; code is a LOINC code."""
    _, decision = authorize("list_observations", patient_id, category)
    wanted = [category] if category else sorted(decision.categories) if decision.categories is not None else []
    parameters = {"patient": decision.patient, "_sort": "-date"}
    if wanted:
        parameters["category"] = ",".join(f"{CATEGORY_SYSTEM}|{value}" for value in wanted)
    if code:
        if not re.fullmatch(r"[0-9]{1,7}-[0-9]", code):
            raise ValueError("code must be a LOINC code such as 4548-4")
        parameters["code"] = f"http://loinc.org|{code}"
    found = await fhir.search("Observation", parameters)
    return [observation_summary(resource) for resource in found if in_scope(resource, decision)]


@mcp.tool(annotations=READ_ONLY)
async def get_observation(observation_id: str, patient_id: str | None = None) -> dict:
    """One observation by id."""
    _, decision = authorize("get_observation", patient_id)
    resource = await fhir.read("Observation", observation_id) if IDENTIFIER.fullmatch(observation_id) else None
    if resource is None or not in_scope(resource, decision):
        return {"found": False}  # the same answer for "does not exist" and "not yours"
    return {"found": True, **observation_summary(resource)}


@mcp.tool(annotations=READ_ONLY)
async def list_medications(patient_id: str | None = None) -> list[dict]:
    """Medication requests for one patient: medication, status and dosage text."""
    _, decision = authorize("list_medications", patient_id)
    found = await fhir.search("MedicationRequest", {"patient": decision.patient})
    return [{"id": r.get("id"), "medication": r.get("medicationCodeableConcept", {}).get("text"), "status": r.get("status"), "dosage": (r.get("dosageInstruction") or [{}])[0].get("text")} for r in found if in_scope(r, decision)]


@mcp.tool(annotations=READ_ONLY)
async def list_conditions(patient_id: str | None = None) -> list[dict]:
    """Conditions on one patient's problem list."""
    _, decision = authorize("list_conditions", patient_id)
    found = await fhir.search("Condition", {"patient": decision.patient})
    return [{"id": r.get("id"), "condition": r.get("code", {}).get("text"), "status": (r.get("clinicalStatus", {}).get("coding") or [{}])[0].get("code")} for r in found if in_scope(r, decision)]


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False))
async def record_observation(category: str, loinc_code: str, display: str, value: float, unit: str, effective: str, patient_id: str | None = None) -> dict:
    """Record one observation for one patient. The record is marked as entered through this server."""
    token, decision = authorize("record_observation", patient_id, category)
    if not re.fullmatch(r"[0-9]{1,7}-[0-9]", loinc_code) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}(T[0-9:+\-Z.]+)?", effective):
        raise ValueError("loinc_code must look like 8867-4 and effective like 2026-04-01")
    resource: dict[str, Any] = {
        "resourceType": "Observation",
        "status": "preliminary",  # a person confirms it in the clinical system, not here
        "category": [{"coding": [{"system": CATEGORY_SYSTEM, "code": category}]}],
        "code": {"coding": [{"system": "http://loinc.org", "code": loinc_code}], "text": display[:120]},
        "subject": {"reference": f"Patient/{decision.patient}"},  # from the decision, never from the arguments alone
        "effectiveDateTime": effective,
        "valueQuantity": {"value": value, "unit": unit[:20]},
        "note": [{"text": f"Recorded through the MCP server by client {token.client_id}"}],
    }
    created = await fhir.create(resource)
    return {"id": created.get("id"), "status": created.get("status"), "patient": decision.patient}


app = mcp.streamable_http_app()

if __name__ == "__main__":
    mcp.run(transport="streamable-http")
