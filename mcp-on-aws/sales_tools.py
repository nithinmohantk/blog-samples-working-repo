"""Business logic shared by the AgentCore Gateway Lambda target and the
AgentCore Runtime MCP server.

The functions here know nothing about MCP. They validate input, read from
DynamoDB, and return small, bounded JSON-serialisable results, so that a tool
call can never flood the model's context window.
"""

from __future__ import annotations

import base64
import json
import os
import re
from decimal import Decimal
from typing import Any

import boto3
from boto3.dynamodb.conditions import Key

MAX_PAGE_SIZE = 25
CUSTOMER_ID_PATTERN = re.compile(r"^C-[0-9]{6}$")

_table = None


class ToolInputError(ValueError):
    """Raised when a tool argument fails validation."""


def _get_table():
    """Create the DynamoDB table resource once per execution environment."""
    global _table
    if _table is None:
        table_name = os.environ["ORDERS_TABLE_NAME"]
        _table = boto3.resource("dynamodb").Table(table_name)
    return _table


def reset_table_cache() -> None:
    """Used by tests that create a fresh table per test."""
    global _table
    _table = None


def _validate_customer_id(customer_id: str) -> str:
    if not isinstance(customer_id, str) or not CUSTOMER_ID_PATTERN.match(customer_id):
        raise ToolInputError("customer_id must look like C-123456")
    return customer_id


def _encode_token(last_key: dict[str, Any] | None) -> str | None:
    if not last_key:
        return None
    raw = json.dumps(last_key, sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def _decode_token(token: str | None, customer_id: str) -> dict[str, Any] | None:
    if not token:
        return None
    try:
        key = json.loads(base64.urlsafe_b64decode(token.encode("ascii")))
    except (ValueError, json.JSONDecodeError) as exc:
        raise ToolInputError("next_token is not valid") from exc
    # A token must not let a caller page into another customer's partition.
    if not isinstance(key, dict) or key.get("customer_id") != customer_id:
        raise ToolInputError("next_token does not belong to this customer")
    return key


def _to_float(value: Any) -> float:
    return float(value) if isinstance(value, Decimal) else float(value or 0)


def get_customer_summary(customer_id: str) -> dict[str, Any]:
    """Return order count and total spend for one customer.

    Reads every order for the customer with a paginated Query and a
    projection, so only the amount attribute crosses the wire.
    """
    customer_id = _validate_customer_id(customer_id)
    table = _get_table()
    total = Decimal("0")
    count = 0
    kwargs: dict[str, Any] = {
        "KeyConditionExpression": Key("customer_id").eq(customer_id),
        "ProjectionExpression": "amount",
    }
    while True:
        page = table.query(**kwargs)
        for item in page.get("Items", []):
            total += Decimal(str(item.get("amount", 0)))
            count += 1
        last_key = page.get("LastEvaluatedKey")
        if not last_key:
            break
        kwargs["ExclusiveStartKey"] = last_key
    return {
        "customer_id": customer_id,
        "order_count": count,
        "total_spend": float(total.quantize(Decimal("0.01"))),
        "currency": "EUR",
    }


def list_customer_orders(
    customer_id: str, limit: int = 10, next_token: str | None = None
) -> dict[str, Any]:
    """Return one page of a customer's orders, newest order id first.

    The page size is clamped to MAX_PAGE_SIZE whatever the model asks for.
    """
    customer_id = _validate_customer_id(customer_id)
    try:
        limit = int(limit)
    except (TypeError, ValueError) as exc:
        raise ToolInputError("limit must be an integer") from exc
    limit = max(1, min(limit, MAX_PAGE_SIZE))

    kwargs: dict[str, Any] = {
        "KeyConditionExpression": Key("customer_id").eq(customer_id),
        "ScanIndexForward": False,
        "Limit": limit,
    }
    start_key = _decode_token(next_token, customer_id)
    if start_key:
        kwargs["ExclusiveStartKey"] = start_key

    page = _get_table().query(**kwargs)
    orders = [
        {
            "order_id": item["order_id"],
            "status": item.get("status", "UNKNOWN"),
            "amount": _to_float(item.get("amount")),
        }
        for item in page.get("Items", [])
    ]
    return {
        "customer_id": customer_id,
        "orders": orders,
        "next_token": _encode_token(page.get("LastEvaluatedKey")),
    }
