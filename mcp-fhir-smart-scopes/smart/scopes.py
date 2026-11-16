"""SMART on FHIR v2 scopes: parse them, and answer one question about a set of them.

    patient/Observation.rs?category=http://terminology.hl7.org/CodeSystem/observation-category|laboratory
    ^context ^resource  ^permissions (c r u d s)        ^optional filter: only resources matching it

SMART v1 scopes are accepted and translated: .read is .rs, .write is .cud, .* is .cruds.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import parse_qsl

PATTERN = re.compile(r"^(patient|user|system)/([A-Z][A-Za-z]+|\*)\.(\*|read|write|c?r?u?d?s?)(?:\?(.+))?$")
V1 = {"read": "rs", "write": "cud", "*": "cruds"}


@dataclass(frozen=True)
class Grant:
    """One granted scope."""

    context: str  # patient, user or system
    resource: str  # a FHIR resource type, or * for all
    permissions: frozenset[str]  # of c, r, u, d, s
    filters: tuple[tuple[str, str], ...] = field(default=())  # search parameters the resource must match

    def covers(self, resource: str, permission: str) -> bool:
        return self.resource in ("*", resource) and permission in self.permissions


def parse(scopes: list[str]) -> list[Grant]:
    """The clinical scopes in a token. Anything else (openid, launch, offline_access) is ignored here."""
    grants = []
    for scope in scopes:
        match = PATTERN.match(scope)
        if not match or not match.group(3):
            continue
        context, resource, permissions, query = match.groups()
        grants.append(Grant(context, resource, frozenset(V1.get(permissions, permissions)), tuple(parse_qsl(query or ""))))
    return grants


def matching(grants: list[Grant], resource: str, permission: str) -> list[Grant]:
    return [grant for grant in grants if grant.covers(resource, permission)]


def allowed_values(grants: list[Grant], parameter: str) -> set[str] | None:
    """The values of one search parameter that these grants are limited to, or None for no limit.

    Scopes add up: one unfiltered grant among them lifts the limit.
    """
    values: set[str] = set()
    for grant in grants:
        own = {value for name, value in grant.filters if name == parameter}
        if not own:
            return None
        values |= own
    return values
