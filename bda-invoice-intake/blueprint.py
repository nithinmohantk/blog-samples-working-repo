"""Build and check an Amazon Bedrock Data Automation (BDA) document blueprint.

A blueprint is a JSON schema (draft-07) whose fields carry a natural-language
``instruction`` and an ``inferenceType``: ``explicit`` for values printed in the
document, ``inferred`` for values BDA must derive. This module builds the
schema from Python objects and checks it against BDA's documented blueprint
limits before it is sent, so a bad blueprint fails in CI rather than at
CreateBlueprint.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

MAX_LEAF_FIELDS = 100          # leaf fields per blueprint
MAX_NAME_LENGTH = 60           # field and blueprint name length
MAX_DOC_INSTRUCTION = 600      # instruction length for document blueprints
MAX_SCHEMA_CHARS = 100_000     # serialized blueprint size
PRICE_FIELD_THRESHOLD = 30     # custom output price covers up to 30 fields
TYPES = {"string", "number", "boolean"}


@dataclass(frozen=True)
class Field:
    name: str
    instruction: str
    type: str = "string"
    inference: str = "explicit"      # "explicit" or "inferred"


@dataclass(frozen=True)
class Table:
    """A repeating group, such as invoice line items, extracted as an array."""
    name: str
    instruction: str
    columns: list[Field] = field(default_factory=list)


def _leaf(f: Field) -> dict[str, Any]:
    return {"type": f.type, "inferenceType": f.inference, "instruction": f.instruction}


def build_blueprint(class_name: str, description: str,
                    fields: list[Field], tables: list[Table] = ()) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "class": class_name,
        "description": description,
        "type": "object",
        "definitions": {},
        "properties": {f.name: _leaf(f) for f in fields},
    }
    for t in tables:
        item = f"{t.name}_item"
        schema["definitions"][item] = {
            "type": "object",
            "properties": {c.name: _leaf(c) for c in t.columns},
        }
        schema["properties"][t.name] = {
            "type": "array",
            "instruction": t.instruction,
            "items": {"$ref": f"#/definitions/{item}"},
        }
    return schema


def leaf_fields(schema: dict[str, Any]) -> list[str]:
    """Names of leaf fields, with table columns as table.column."""
    names: list[str] = []
    for name, prop in schema["properties"].items():
        if prop.get("type") == "array":
            ref = prop["items"]["$ref"].rsplit("/", 1)[1]
            names += [f"{name}.{c}" for c in schema["definitions"][ref]["properties"]]
        else:
            names.append(name)
    return names


def check_blueprint(schema: dict[str, Any]) -> list[str]:
    """Return problems that would make CreateBlueprint fail or extraction unreliable."""
    problems: list[str] = []
    leaves = leaf_fields(schema)
    if len(leaves) > MAX_LEAF_FIELDS:
        problems.append(f"{len(leaves)} leaf fields; the limit is {MAX_LEAF_FIELDS}")
    if len(json.dumps(schema)) > MAX_SCHEMA_CHARS:
        problems.append(f"schema is over {MAX_SCHEMA_CHARS} characters")

    def visit(props: dict[str, Any], path: str) -> None:
        for name, prop in props.items():
            where = f"{path}{name}"
            if "/" in name or len(name) > MAX_NAME_LENGTH:
                problems.append(f"{where}: names must be at most {MAX_NAME_LENGTH} characters and contain no '/'")
            instruction = prop.get("instruction", "")
            if not instruction.strip():
                problems.append(f"{where}: missing instruction")
            elif len(instruction) > MAX_DOC_INSTRUCTION:
                problems.append(f"{where}: instruction longer than {MAX_DOC_INSTRUCTION} characters")
            if prop.get("type") == "array":
                continue
            if prop.get("type") not in TYPES:
                problems.append(f"{where}: type must be one of {sorted(TYPES)}")
            if prop.get("inferenceType") not in {"explicit", "inferred"}:
                problems.append(f"{where}: inferenceType must be explicit or inferred")

    visit(schema["properties"], "")
    for item, definition in schema["definitions"].items():
        visit(definition["properties"], f"{item}.")
    return problems


INVOICE = build_blueprint(
    "supplier_invoice",
    "Supplier invoices received by accounts payable, one invoice per document",
    fields=[
        Field("invoice_number", "The invoice number or invoice ID as printed"),
        Field("invoice_date", "The invoice date, formatted YYYY-MM-DD", inference="inferred"),
        Field("supplier_name", "The legal name of the company issuing the invoice"),
        Field("supplier_vat_number", "The supplier's VAT registration number, without spaces",
              inference="inferred"),
        Field("currency", "The ISO 4217 currency code of the amounts, such as EUR or GBP",
              inference="inferred"),
        Field("net_total", "The total before VAT", type="number"),
        Field("vat_total", "The total VAT charged", type="number"),
        Field("gross_total", "The total amount payable including VAT", type="number"),
        Field("purchase_order_number", "The customer's purchase order number, if one is quoted"),
    ],
    tables=[Table("line_items", "Each billed line on the invoice", columns=[
        Field("description", "Description of the goods or service"),
        Field("quantity", "Quantity billed", type="number"),
        Field("unit_price", "Price per unit before VAT", type="number"),
        Field("line_total", "Line amount before VAT", type="number"),
    ])],
)


def create_blueprint(client: Any, name: str, schema: dict[str, Any]) -> str:
    """Create the blueprint in the DEVELOPMENT stage and return its ARN."""
    problems = check_blueprint(schema)
    if problems:
        raise ValueError("; ".join(problems))
    resp = client.create_blueprint(blueprintName=name, type="DOCUMENT",
                                   blueprintStage="DEVELOPMENT", schema=json.dumps(schema))
    return resp["blueprint"]["blueprintArn"]
