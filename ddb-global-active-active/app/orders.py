"""Order writes for a DynamoDB global table in MREC mode, using the
"write to your Region" (mixed primary) pattern.

- Creates are idempotent: the client's idempotency key is the item key, and a
  conditional put means a retry, or the same request arriving in two Regions,
  creates the item once (after replication; see the article for the window).
- Every order has a home Region, set when it is created. Updates are accepted
  only in that Region, so concurrent updates to one order never race across
  Regions and last-writer-wins never has to choose between them.
- Updates use an optimistic version check. In MREC mode condition expressions
  are evaluated against the local replica, which is exactly why updates must
  stay in the home Region.
"""

from __future__ import annotations

import hashlib
import json
import time
from decimal import Decimal
from typing import Any

from botocore.exceptions import ClientError

ALLOWED_STATUS = {"PLACED", "PAID", "SHIPPED", "CANCELLED"}


class OrderError(Exception):
    status = 400


class Conflict(OrderError):
    status = 409


class NotFound(OrderError):
    status = 404


class WrongHomeRegion(OrderError):
    """The order must be updated in another Region."""

    status = 421  # Misdirected Request

    def __init__(self, home_region: str):
        super().__init__(f"order is homed in {home_region}")
        self.home_region = home_region


def _fingerprint(customer_id: str, amount: Decimal) -> str:
    raw = json.dumps({"c": customer_id, "a": str(amount)}, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()


def _parse_amount(value: Any) -> Decimal:
    try:
        amount = Decimal(str(value))
    except Exception as exc:  # noqa: BLE001
        raise OrderError("amount must be a number") from exc
    if amount <= 0 or amount.as_tuple().exponent < -2:
        raise OrderError("amount must be positive with at most two decimals")
    return amount


def create_order(table, region: str, idempotency_key: str, customer_id: str,
                 amount: Any, now_ms: int | None = None) -> tuple[dict[str, Any], bool]:
    """Return (order, created). created is False for an idempotent replay."""
    if not idempotency_key or len(idempotency_key) > 64:
        raise OrderError("Idempotency-Key header is required (max 64 chars)")
    if not customer_id:
        raise OrderError("customer_id is required")
    amount = _parse_amount(amount)
    fp = _fingerprint(customer_id, amount)
    now_ms = now_ms or int(time.time() * 1000)
    item = {
        "pk": f"ORDER#{idempotency_key}",
        "customer_id": customer_id,
        "amount": amount,
        "status": "PLACED",
        "version": 1,
        "home_region": region,
        "request_fingerprint": fp,
        "created_at_ms": now_ms,
        "updated_at_ms": now_ms,
        "updated_in": region,
    }
    try:
        table.put_item(Item=item, ConditionExpression="attribute_not_exists(pk)")
        return item, True
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
    existing = table.get_item(Key={"pk": item["pk"]}, ConsistentRead=True).get("Item")
    if existing is None:  # deleted between the put and the get
        raise Conflict("order changed concurrently; retry")
    if existing.get("request_fingerprint") != fp:
        raise Conflict("idempotency key reused with a different request")
    return existing, False


def update_status(table, region: str, order_id: str, new_status: str,
                  expected_version: int, now_ms: int | None = None) -> dict[str, Any]:
    if new_status not in ALLOWED_STATUS:
        raise OrderError(f"status must be one of {sorted(ALLOWED_STATUS)}")
    key = {"pk": f"ORDER#{order_id}"}
    current = table.get_item(Key=key, ConsistentRead=True).get("Item")
    if current is None:
        raise NotFound("order not found")
    if current["home_region"] != region:
        raise WrongHomeRegion(current["home_region"])
    now_ms = now_ms or int(time.time() * 1000)
    try:
        resp = table.update_item(
            Key=key,
            UpdateExpression="SET #s = :s, version = version + :one, updated_at_ms = :t, updated_in = :r",
            ConditionExpression="version = :v AND home_region = :r",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":s": new_status, ":one": 1, ":t": now_ms,
                                       ":v": expected_version, ":r": region},
            ReturnValues="ALL_NEW",
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            raise Conflict("version mismatch; read the order and retry") from exc
        raise
    return resp["Attributes"]
