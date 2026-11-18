"""Two versions of the tool people reach for first: one tool that takes any FHIR query.

fhir_request_naive  checks the resource type and the permission against the scopes, and adds the patient to searches.
fhir_request_guarded  also allow-lists search parameters, refuses anything that can pull in other resources,
                      and checks every resource that comes back.

Both run on the same token verification as the real server. They exist to be measured, not used.
"""
from __future__ import annotations

import os
from urllib.parse import parse_qsl, urlencode, urlsplit

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP

from server.fhir import Fhir
from server.policy import CATEGORY_SYSTEM, Decision, Denied, in_scope
from server.tokens import JwtVerifier
from smart.scopes import allowed_values, matching, parse

ISSUER, AUDIENCE = os.environ["MCP_ISSUER"], os.environ["MCP_AUDIENCE"]
fhir = Fhir(os.environ["FHIR_BASE"])
with open(os.environ["MCP_PUBLIC_KEY_FILE"], encoding="utf-8") as handle:
    verifier = JwtVerifier(handle.read(), ISSUER, AUDIENCE)
mcp = FastMCP("fhir-generic", port=int(os.environ.get("MCP_PORT", "8001")), stateless_http=True, json_response=True, token_verifier=verifier, auth=AuthSettings(issuer_url=ISSUER, resource_server_url=AUDIENCE))

ALLOWED_PARAMETERS = {"Patient": set(), "Observation": {"category", "code", "date"}, "MedicationRequest": {"status"}, "Condition": {"clinical-status"}}


def split(path: str) -> tuple[str, str | None, list[tuple[str, str]], list[str]]:
    url = urlsplit(path)
    parts = [part for part in url.path.split("/") if part]
    if not parts:
        raise Denied("lab", "empty path")
    return parts[0], parts[1] if len(parts) > 1 else None, parse_qsl(url.query), parts[2:]


@mcp.tool()
async def fhir_request_naive(path: str) -> dict:
    """GET any FHIR path, for example Observation?code=4548-4 or Patient/123."""
    token = get_access_token()
    resource, identifier, query, _ = split(path)
    grants = matching(parse(token.scopes), resource, "r" if identifier else "s")
    if not grants:
        raise Denied("lab", "no scope for this resource type")
    if not identifier and resource != "Patient" and all(grant.context == "patient" for grant in grants):
        query = [(name, value) for name, value in query if name not in ("patient", "subject")] + [("patient", token.patient)]
        path = f"{resource}?{urlencode(query)}"
    return await fhir.raw(path)


@mcp.tool()
async def fhir_request_guarded(path: str) -> dict:
    """GET a FHIR read or a simple search. Only plain search parameters are accepted."""
    token = get_access_token()
    resource, identifier, query, rest = split(path)
    grants = matching(parse(token.scopes), resource, "r" if identifier else "s")
    if not grants or resource not in ALLOWED_PARAMETERS:
        raise Denied("lab", "no scope for this resource type")
    if rest or (identifier and (identifier.startswith(("$", "_")) or query)):
        raise Denied("lab", "operations, history and anything after the id are refused")
    if any(grant.context != "patient" for grant in grants):
        raise Denied("lab", "this lab tool only serves patient-level tokens")
    categories = allowed_values(grants, "category") if resource == "Observation" else None
    if categories is not None:
        categories = {value.removeprefix(CATEGORY_SYSTEM + "|") for value in categories}
    decision = Decision(token.patient, categories)
    if identifier:
        found = await fhir.read(resource, identifier)
        return found if found is not None and in_scope(found, decision) else {"resourceType": "OperationOutcome", "status": 404}
    for name, _ in query:
        if name not in ALLOWED_PARAMETERS[resource]:  # no _include, _revinclude, _has, chains, modifiers or patient
            raise Denied("lab", f"search parameter {name} is not on the allow-list")
    forced = [("_id", token.patient)] if resource == "Patient" else [("patient", token.patient)]
    if categories is not None:
        asked = {value.split("|")[-1] for name, value in query if name == "category"}
        if asked - categories:
            raise Denied("lab", "category outside the grant")
        if not asked:
            forced.append(("category", ",".join(f"{CATEGORY_SYSTEM}|{value}" for value in sorted(categories))))
    bundle = await fhir.raw(f"{resource}?{urlencode(query + forced)}")
    entries = [entry for entry in bundle.get("entry", []) if entry.get("resource", {}).get("resourceType") == resource and in_scope(entry["resource"], decision)]
    return {"resourceType": "Bundle", "type": "searchset", "entry": [{"resource": entry["resource"]} for entry in entries]}


app = mcp.streamable_http_app()
