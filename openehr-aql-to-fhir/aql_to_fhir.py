"""
aql_to_fhir.py
Maps an openEHR AQL result set of medication orders to a FHIR R4 transaction Bundle of
MedicationRequest resources. The mapping is data: a list of rules a clinical modeller can read.
"""
import json
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import quote

IDENTIFIER_SYSTEM = "urn:openehr:medication-order"
TERMINOLOGIES = {"SNOMED-CT": "http://snomed.info/sct", "LOINC": "http://loinc.org"}

# openEHR instruction state (ISM) -> MedicationRequest.status. A clinical decision: review before use.
ISM_TO_STATUS = {
    "524": "draft", "526": "active", "529": "active", "245": "active",
    "527": "on-hold", "530": "on-hold", "528": "cancelled", "531": "stopped",
    "532": "completed", "533": "stopped",
}


@dataclass
class Report:
    mapped_rows: int = 0
    rejected: list[str] = field(default_factory=list)       # rows that produced no resource, with the reason
    notes: list[str] = field(default_factory=list)          # resources produced with something degraded
    unmapped_columns: list[str] = field(default_factory=list)


def set_path(resource: dict, path: str, value: Any) -> None:
    """Sets 'a.b[0].c' on a nested dict, creating objects and list slots as needed."""
    node: Any = resource
    parts = path.split(".")
    for i, part in enumerate(parts):
        name, _, index = part.partition("[")
        last = i == len(parts) - 1
        if index:
            slot = int(index.rstrip("]"))
            items = node.setdefault(name, [])
            while len(items) <= slot:
                items.append({})
            if last:
                items[slot] = value
            else:
                node = items[slot]
        elif last:
            node[name] = value
        else:
            node = node.setdefault(name, {})


# ---- transforms: (cell value, order id, report) -> FHIR value, or None to leave the element out
def text(value: Any, order: str, report: Report) -> Any:
    return value or None


def codeable(value: Any, order: str, report: Report) -> Any:
    """DV_TEXT / DV_CODED_TEXT -> CodeableConcept. Unknown terminologies keep the text and are reported."""
    if not value:
        return None
    concept: dict[str, Any] = {"text": value["value"]}
    code = value.get("defining_code")
    if not code:
        report.notes.append(f"{order}: '{value['value']}' is uncoded text")
        return concept
    system = TERMINOLOGIES.get(code["terminology_id"]["value"])
    if system is None:
        report.notes.append(f"{order}: terminology '{code['terminology_id']['value']}' has no FHIR system; code dropped")
        return concept
    concept["coding"] = [{"system": system, "code": code["code_string"], "display": value["value"]}]
    return concept


@dataclass(frozen=True)
class Rule:
    column: str
    fhir_path: str
    transform: Callable[[Any, str, Report], Any] = text
    required: bool = False


MEDICATION_ORDER_RULES = [
    Rule("medication", "medicationCodeableConcept", codeable, required=True),
    Rule("authored", "authoredOn"),
    Rule("directions", "dosageInstruction[0].text"),
    Rule("route", "dosageInstruction[0].route", codeable),
    Rule("start", "dosageInstruction[0].timing.repeat.boundsPeriod.start"),
    Rule("stop", "dosageInstruction[0].timing.repeat.boundsPeriod.end"),
    Rule("indication", "reasonCode[0].text"),
]
STRUCTURAL_COLUMNS = {"ehr_id", "composition_uid", "order_id"}       # used for identity, not clinical content


def latest_states(actions: dict) -> dict[str, str]:
    """The current state of an order is the state of its most recent ACTION, not a field on the order."""
    names = [c["name"] for c in actions["columns"]]
    latest: dict[str, tuple[str, str]] = {}
    for row in actions["rows"]:
        record = dict(zip(names, row))
        if record["order_id"] not in latest or record["time"] > latest[record["order_id"]][0]:
            latest[record["order_id"]] = (record["time"], record["state"])
    return {order: state for order, (_, state) in latest.items()}


def medication_orders_to_bundle(orders: dict, actions: dict, patient_index: dict[str, str]) -> tuple[dict, Report]:
    report, entries = Report(), []
    names = [c["name"] for c in orders["columns"]]
    used = {r.column for r in MEDICATION_ORDER_RULES} | STRUCTURAL_COLUMNS
    report.unmapped_columns = [n for n in names if n not in used]
    states = latest_states(actions)

    for row in orders["rows"]:
        record = dict(zip(names, row))
        order = record.get("order_id") or "(no order id)"
        patient_id = patient_index.get(record["ehr_id"])
        if patient_id is None:
            report.rejected.append(f"{order}: no FHIR Patient for EHR {record['ehr_id']}")
            continue
        missing = [r.column for r in MEDICATION_ORDER_RULES if r.required and not record.get(r.column)]
        if missing or not record.get("order_id"):
            report.rejected.append(f"{order}: missing required {', '.join(missing) or 'order_id'}")
            continue

        state = states.get(order)
        status = ISM_TO_STATUS.get(state or "", "unknown")
        if status == "unknown":
            report.notes.append(f"{order}: no usable state from ACTION entries; status set to unknown")

        # The identifier is stable across composition versions, so a new version replaces the resource.
        versioned_object = record["composition_uid"].rsplit("::", 1)[0]
        identifier = f"{versioned_object}:{order}"
        resource: dict[str, Any] = {
            "resourceType": "MedicationRequest",
            "meta": {"source": f"urn:openehr:composition:{record['composition_uid']}"},
            "identifier": [{"system": IDENTIFIER_SYSTEM, "value": identifier}],
            "status": status,
            "intent": "order",
            "subject": {"reference": f"Patient/{patient_id}"},
        }
        for rule in MEDICATION_ORDER_RULES:
            value = rule.transform(record.get(rule.column), order, report)
            if value is not None:
                set_path(resource, rule.fhir_path, value)
        for column in report.unmapped_columns:
            if record.get(column):
                report.notes.append(f"{order}: column '{column}' has a value and no mapping rule")

        entries.append({
            "resource": resource,
            # Conditional update: running the same batch twice creates nothing new.
            "request": {"method": "PUT",
                        "url": f"MedicationRequest?identifier={quote(IDENTIFIER_SYSTEM, safe='')}%7C{quote(identifier, safe='')}"},
        })
        report.mapped_rows += 1
    return {"resourceType": "Bundle", "type": "transaction", "entry": entries}, report


if __name__ == "__main__":
    bundle, rep = medication_orders_to_bundle(
        json.load(open("medication_orders.json", encoding="utf-8")),
        json.load(open("medication_actions.json", encoding="utf-8")),
        {"ehr-aaa": "pat-001"})
    print(json.dumps(bundle, indent=2, sort_keys=True))
