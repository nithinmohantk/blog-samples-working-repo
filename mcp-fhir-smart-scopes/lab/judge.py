"""Decide, from outside the server, whether an answer contained anything the token did not permit.

Written apart from server/policy.py on purpose: it looks records up in the lab's own data by type and id.
"""
from __future__ import annotations

from lab.data import resources
from smart.scopes import parse

CATEGORY_PREFIX = "http://terminology.hl7.org/CodeSystem/observation-category|"
KNOWN = {(r["resourceType"], r["id"]): r for r in resources()}


def references(payload: object) -> set[tuple[str, str]]:
    """Every (type, id) of the lab's records that appears in an answer, whether as a resource or as a summary."""
    found: set[tuple[str, str]] = set()
    if isinstance(payload, dict):
        if "resourceType" in payload and (payload["resourceType"], payload.get("id")) in KNOWN:
            found.add((payload["resourceType"], payload["id"]))
        elif isinstance(payload.get("id"), str):
            found |= {key for key in KNOWN if key[1] == payload["id"]}
        for value in payload.values():
            found |= references(value)
    elif isinstance(payload, list):
        for item in payload:
            found |= references(item)
    return found


def violations(scopes: list[str], token_patient: str | None, payload: object) -> list[str]:
    grants = parse(scopes)
    wrong = []
    for kind, identifier in sorted(references(payload)):
        record = KNOWN[(kind, identifier)]
        owner = identifier if kind == "Patient" else record["subject"]["reference"].removeprefix("Patient/")
        category = {c["code"] for concept in record.get("category", []) for c in concept["coding"]}
        permitted = False
        for grant in grants:
            if grant.resource not in ("*", kind) or not grant.permissions & {"r", "s"}:
                continue
            if grant.context == "patient" and owner != token_patient:
                continue
            limits = {value.removeprefix(CATEGORY_PREFIX) for name, value in grant.filters if name == "category"}
            if limits and not category & limits:
                continue
            permitted = True
        if not permitted:
            wrong.append(f"{kind}/{identifier}")
    return wrong
