"""
view_runner.py
A minimal SQL on FHIR ViewDefinition runner: enough to show how the specification turns FHIR
resources into tables. It supports resource, where, select with column, forEach and forEachOrNull,
sibling-select cross joins, getResourceKey() and getReferenceKey(). It is NOT a conformant runner:
no unionAll, no nested select, no constants, no type checking.
"""
import itertools
import re
from typing import Any

from fhirpathpy import evaluate

_REFERENCE_KEY = re.compile(r"^(?P<prefix>.+)\.getReferenceKey\((?P<type>\w*)\)$")


def _column(node: dict, resource: dict, path: str) -> Any:
    if path == "getResourceKey()":
        return resource["id"]
    match = _REFERENCE_KEY.match(path)
    if match:
        refs = evaluate(node, match["prefix"] + ".reference")
        if not refs:
            return None
        kind, _, key = refs[0].partition("/")              # relative literal references only
        return key if not match["type"] or kind == match["type"] else None
    values = evaluate(node, path)
    return values[0] if values else None


def _select_rows(select: dict, resource: dict) -> list[dict]:
    each = select.get("forEach") or select.get("forEachOrNull")
    nodes = evaluate(resource, each) if each else [resource]
    if not nodes and "forEachOrNull" in select:
        return [{c["name"]: None for c in select.get("column", [])}]
    return [{c["name"]: _column(node, resource, c["path"]) for c in select.get("column", [])} for node in nodes]


def run_view(view: dict, resources: list[dict]) -> list[dict]:
    rows = []
    for resource in resources:
        if resource["resourceType"] != view["resource"]:
            continue
        if not all(evaluate(resource, w["path"]) == [True] for w in view.get("where", [])):
            continue
        parts = [_select_rows(select, resource) for select in view["select"]]
        for combination in itertools.product(*parts):       # sibling selects are cross joined
            rows.append({k: v for part in combination for k, v in part.items()})
    return rows
