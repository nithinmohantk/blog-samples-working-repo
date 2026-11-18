"""Free-text clinical note to coded FHIR Condition and Observation resources, with a human in the middle.

The model is only ever asked for one thing: a JSON document that matches build_schema(). Everything after that
is ordinary code. guard() decides what a reviewer is shown, apply_review() decides what the reviewer accepted,
and to_bundle() writes FHIR for accepted items only.
"""
from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal, InvalidOperation

SNOMED = "http://snomed.info/sct"
LOINC = "http://loinc.org"
UCUM = "http://unitsofmeasure.org"
ASSERTIONS = ["present", "absent", "uncertain", "family_history"]
UNCODED = "uncoded"
OTHER_UNIT = "other"
UNSUPPORTED_KEYWORDS = {
    "minLength", "maxLength", "pattern", "format", "minimum", "maximum", "multipleOf", "patternProperties",
    "unevaluatedProperties", "propertyNames", "minProperties", "maxProperties", "unevaluatedItems", "contains",
    "minContains", "maxContains", "minItems", "maxItems", "uniqueItems",
}


class ShapeError(ValueError):
    """The response is not a document of the agreed shape. Nothing in it is used."""


class ReviewError(ValueError):
    """A review decision that the rules do not allow."""


def load_subset(path: str) -> dict:
    with open(path, encoding="utf-8") as handle:
        subset = json.load(handle)
    return {"conditions": {c["code"]: c for c in subset["conditions"]},
            "observations": {o["code"]: o for o in subset["observations"]}}


def build_schema(subset: dict) -> dict:
    """The schema sent as response_format. Its enums are the subset: the model cannot return any other code."""
    units = sorted({o["unit"] for o in subset["observations"].values()}) + [OTHER_UNIT]
    evidence = {"type": "string", "description": "Exact words copied from the note that support this item. No paraphrase."}
    return {
        "type": "object", "additionalProperties": False, "required": ["conditions", "observations"],
        "properties": {
            "conditions": {"type": "array", "items": {
                "type": "object", "additionalProperties": False, "required": ["evidence", "code", "assertion"],
                "properties": {
                    "evidence": evidence,
                    "code": {"type": "string", "enum": list(subset["conditions"]) + [UNCODED],
                             "description": "SNOMED CT code from the list in the instructions, or 'uncoded' when none fits."},
                    "assertion": {"type": "string", "enum": ASSERTIONS,
                                  "description": "present: the patient has it. absent: the note rules it out. uncertain: suspected or queried. family_history: about a relative."},
                }}},
            "observations": {"type": "array", "items": {
                "type": "object", "additionalProperties": False, "required": ["evidence", "code", "value", "unit"],
                "properties": {
                    "evidence": evidence,
                    "code": {"type": "string", "enum": list(subset["observations"]), "description": "LOINC code from the list in the instructions."},
                    "value": {"type": "number", "description": "The number as written in the note. Do not convert units."},
                    "unit": {"type": "string", "enum": units, "description": "UCUM unit as written in the note, or 'other' when the note uses a different unit."},
                }}},
        },
    }


def lint_schema(schema: dict) -> list[str]:
    """Check the schema against the documented limits of strict structured outputs."""
    problems: list[str] = []
    count = 0

    def walk(node: dict, path: str, depth: int) -> None:
        nonlocal count
        for keyword in UNSUPPORTED_KEYWORDS & node.keys():
            problems.append(f"{path}: keyword '{keyword}' is not supported")
        if node.get("type") == "object":
            if depth > 5:
                problems.append(f"{path}: more than five levels of nesting")
            properties = node.get("properties", {})
            count += len(properties)
            if node.get("additionalProperties") is not False:
                problems.append(f"{path}: additionalProperties must be false")
            if sorted(node.get("required", [])) != sorted(properties):
                problems.append(f"{path}: every property must be listed in required")
            for name, child in properties.items():
                walk(child, f"{path}.{name}", depth + 1)
        elif node.get("type") == "array":
            walk(node["items"], f"{path}[]", depth)

    if schema.get("type") != "object":
        problems.append("$: the root must be an object")
    walk(schema, "$", 1)
    if count > 100:
        problems.append(f"$: {count} properties, the limit is 100")
    return problems


def system_prompt(subset: dict) -> str:
    lines = [
        "You extract coded findings from one clinical note for a clinician to review.",
        "Return only items the note states. Copy the supporting words exactly into 'evidence'.",
        "Use only the codes listed here. If a condition is stated and no code fits, use 'uncoded'.",
        "Do not convert units and do not calculate values.", "", "Conditions (SNOMED CT):"]
    lines += [f"  {c['code']}  {c['display']}  ({c['hint']})" for c in subset["conditions"].values()]
    lines += ["", "Measurements (LOINC, with the only unit accepted):"]
    lines += [f"  {o['code']}  {o['display']}  [{o['unit']}]" for o in subset["observations"].values()]
    return "\n".join(lines)


def parse_response(raw: str, subset: dict) -> dict:
    """Defence in depth: check the shape again even though the service enforces the schema."""
    try:
        document = json.loads(raw, parse_float=Decimal, parse_int=Decimal)
    except json.JSONDecodeError as error:
        raise ShapeError(f"not JSON: {error.msg}") from error
    if not isinstance(document, dict) or set(document) != {"conditions", "observations"}:
        raise ShapeError("the document must have exactly 'conditions' and 'observations'")
    condition_codes = set(subset["conditions"]) | {UNCODED}
    units = {o["unit"] for o in subset["observations"].values()} | {OTHER_UNIT}
    for kind, keys in (("conditions", {"evidence", "code", "assertion"}), ("observations", {"evidence", "code", "value", "unit"})):
        if not isinstance(document[kind], list):
            raise ShapeError(f"'{kind}' must be an array")
        for index, item in enumerate(document[kind]):
            where = f"{kind}[{index}]"
            if not isinstance(item, dict) or set(item) != keys:
                raise ShapeError(f"{where} must have exactly: {', '.join(sorted(keys))}")
            if not isinstance(item["evidence"], str) or not isinstance(item["code"], str):
                raise ShapeError(f"{where}: evidence and code must be strings")
            if kind == "conditions":
                if item["code"] not in condition_codes:
                    raise ShapeError(f"{where}: code '{item['code']}' is not in the subset")
                if item["assertion"] not in ASSERTIONS:
                    raise ShapeError(f"{where}: unknown assertion")
            else:
                if item["code"] not in subset["observations"]:
                    raise ShapeError(f"{where}: code '{item['code']}' is not in the subset")
                if not isinstance(item["value"], Decimal):
                    raise ShapeError(f"{where}: value must be a number")
                if item["unit"] not in units:
                    raise ShapeError(f"{where}: unknown unit")
    return document


def squash(text: str) -> str:
    return " ".join(text.split())


def numbers_in(text: str) -> list[Decimal]:
    found = []
    for token in re.findall(r"\d+(?:[.,]\d+)?", text):
        try:
            found.append(Decimal(token.replace(",", ".")))
        except InvalidOperation:
            pass
    return found


def guard(document: dict, note_text: str, subset: dict) -> list[dict]:
    """Turn a well-formed response into proposals, and stop the ones that cannot be supported from the note."""
    note = squash(note_text)
    proposals: list[dict] = []
    seen: set[tuple] = set()
    for index, item in enumerate(document["conditions"], start=1):
        proposal = {"id": f"c{index}", "kind": "condition", "code": None, "display": None, "assertion": item["assertion"],
                    "evidence": item["evidence"], "status": "for_review", "reasons": [], "flags": []}
        if item["code"] != UNCODED:
            proposal["code"] = item["code"]
            proposal["display"] = subset["conditions"][item["code"]]["display"]
        else:
            proposal["flags"].append("no code in the subset fits: code by hand or reject")
        key = ("condition", item["code"], item["assertion"], squash(item["evidence"]))
        if not squash(item["evidence"]) or squash(item["evidence"]) not in note:
            proposal["status"] = "blocked"
            proposal["reasons"].append("the evidence is not text from the note")
        elif key in seen:
            proposal["status"] = "duplicate"
            proposal["reasons"].append("same item as an earlier one")
        elif item["assertion"] in ("absent", "family_history"):
            proposal["status"] = "not_proposed"
            proposal["reasons"].append("the note rules this out" if item["assertion"] == "absent" else "this is about a relative, not the patient")
        seen.add(key)
        proposals.append(proposal)
    for index, item in enumerate(document["observations"], start=1):
        definition = subset["observations"][item["code"]]
        proposal = {"id": f"o{index}", "kind": "observation", "code": item["code"], "display": definition["display"],
                    "value": item["value"], "unit": item["unit"], "evidence": item["evidence"], "status": "for_review",
                    "reasons": [], "flags": []}
        key = ("observation", item["code"], item["value"], squash(item["evidence"]))
        if not squash(item["evidence"]) or squash(item["evidence"]) not in note:
            proposal["status"] = "blocked"
            proposal["reasons"].append("the evidence is not text from the note")
        elif item["value"] not in numbers_in(item["evidence"]):
            proposal["status"] = "blocked"
            proposal["reasons"].append("the value does not appear in the evidence")
        elif item["unit"] != definition["unit"]:
            proposal["status"] = "blocked"
            proposal["reasons"].append(f"only {definition['unit']} is accepted for this code: enter by hand")
        elif key in seen:
            proposal["status"] = "duplicate"
            proposal["reasons"].append("same item as an earlier one")
        elif not Decimal(str(definition["low"])) <= item["value"] <= Decimal(str(definition["high"])):
            proposal["flags"].append(f"outside the expected range {definition['low']} to {definition['high']} {definition['unit']}: check the source")
        seen.add(key)
        proposals.append(proposal)
    return proposals


def apply_review(proposals: list[dict], decisions: list[dict], subset: dict) -> list[dict]:
    """Return the accepted items. A proposal with no decision stays pending and produces nothing."""
    by_id = {p["id"]: p for p in proposals}
    accepted: list[dict] = []
    decided: set[str] = set()
    for decision in decisions:
        proposal = by_id.get(decision["proposal"])
        action = decision["action"]
        if proposal is None:
            raise ReviewError(f"no proposal '{decision['proposal']}'")
        if proposal["id"] in decided:
            raise ReviewError(f"proposal '{proposal['id']}' already has a decision")
        if proposal["status"] != "for_review":
            raise ReviewError(f"proposal '{proposal['id']}' is {proposal['status']} and cannot be decided")
        if action == "reject":
            decided.add(proposal["id"])
            continue
        item = dict(proposal)
        if action == "recode":
            if proposal["kind"] != "condition" or decision.get("code") not in subset["conditions"]:
                raise ReviewError("a recode needs a condition code from the subset")
            item["code"] = decision["code"]
            item["display"] = subset["conditions"][decision["code"]]["display"]
            item["verification"] = "confirmed"
        elif action == "accept_provisional":
            if proposal["kind"] != "condition":
                raise ReviewError("only a condition can be accepted as provisional")
            item["verification"] = "provisional"
        elif action == "accept":
            item["verification"] = "confirmed"
        else:
            raise ReviewError(f"unknown action '{action}'")
        if item["code"] is None:
            raise ReviewError(f"proposal '{proposal['id']}' has no code: recode or reject it")
        decided.add(proposal["id"])
        accepted.append(item)
    return accepted


def stable_uuid(*parts: str) -> str:
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return f"{digest[0:8]}-{digest[8:12]}-{digest[12:16]}-{digest[16:20]}-{digest[20:32]}"


def number(value: Decimal):
    return int(value) if value == value.to_integral_value() else float(value)


def to_bundle(accepted: list[dict], note: dict, review: dict, subset: dict) -> dict:
    """A transaction Bundle: the accepted resources and one Provenance that names the reviewer and the device."""
    entries, targets = [], []
    for item in accepted:
        uuid = stable_uuid(note["document"], item["kind"], item["code"], item["evidence"])
        annotation = [{"text": f"Source text: \"{squash(item['evidence'])}\""}]
        if item["kind"] == "condition":
            resource = {
                "resourceType": "Condition",
                "clinicalStatus": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-clinical", "code": "active"}]},
                "verificationStatus": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-ver-status", "code": item["verification"]}]},
                "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-category", "code": "encounter-diagnosis"}]}],
                "code": {"coding": [{"system": SNOMED, "code": item["code"], "display": item["display"]}]},
                "subject": {"reference": note["patient"]},
                "recordedDate": review["at"],
                "asserter": {"reference": review["reviewer"]["reference"], "display": review["reviewer"]["display"]},
                "note": annotation,
            }
        else:
            definition = subset["observations"][item["code"]]
            resource = {
                "resourceType": "Observation",
                "status": "final",
                "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/observation-category", "code": definition["category"]}]}],
                "code": {"coding": [{"system": LOINC, "code": item["code"], "display": item["display"]}]},
                "subject": {"reference": note["patient"]},
                "effectiveDateTime": note["date"],
                "performer": [{"reference": review["reviewer"]["reference"], "display": review["reviewer"]["display"]}],
                "valueQuantity": {"value": number(item["value"]), "unit": item["unit"], "system": UCUM, "code": item["unit"]},
                "note": annotation,
            }
        targets.append({"reference": f"urn:uuid:{uuid}"})
        entries.append({"fullUrl": f"urn:uuid:{uuid}", "resource": resource, "request": {"method": "POST", "url": resource["resourceType"]}})
    if entries:
        provenance = {
            "resourceType": "Provenance",
            "target": targets,
            "recorded": review["at"],
            "agent": [
                {"type": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/provenance-participant-type", "code": "verifier"}]},
                 "who": {"reference": review["reviewer"]["reference"], "display": review["reviewer"]["display"]}},
                {"type": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/provenance-participant-type", "code": "assembler"}]},
                 "who": {"reference": review["device"]["reference"], "display": review["device"]["display"]}},
            ],
            "entity": [{"role": "source", "what": {"reference": note["document"]}}],
        }
        uuid = stable_uuid(note["document"], "provenance", review["at"])
        entries.append({"fullUrl": f"urn:uuid:{uuid}", "resource": provenance, "request": {"method": "POST", "url": "Provenance"}})
    return {"resourceType": "Bundle", "type": "transaction", "entry": entries}
