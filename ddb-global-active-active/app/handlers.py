"""Lambda handlers behind a Regional API Gateway HTTP API (payload v2.0).

The same code is deployed to every Region. Each function talks only to the
replica in its own Region (AWS_REGION), so a Regional failure stays inside
that Region.
"""

from __future__ import annotations

import json
import logging
import os
from decimal import Decimal
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

try:
    from . import orders
except ImportError:  # packaged flat in the Lambda zip
    import orders  # type: ignore

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

REGION = os.environ.get("AWS_REGION", "eu-west-1")
TABLE_NAME = os.environ.get("TABLE_NAME", "orders")
CANARY_KEY = {"pk": "HEALTH#canary"}

# API calls: a few retries with the SDK's standard backoff and jitter.
_api_cfg = Config(region_name=REGION, retries={"mode": "standard", "max_attempts": 3},
                  connect_timeout=2, read_timeout=3)
# Health checks: fail fast, so Route 53 sees a slow replica as unhealthy.
_health_cfg = Config(region_name=REGION, retries={"mode": "standard", "max_attempts": 1},
                     connect_timeout=1, read_timeout=1)

_table = boto3.resource("dynamodb", config=_api_cfg).Table(TABLE_NAME)
_health_table = boto3.resource("dynamodb", config=_health_cfg).Table(TABLE_NAME)


def _default(o: Any) -> Any:
    # DynamoDB returns numbers as Decimal. Whole numbers become JSON integers;
    # money stays an exact decimal string rather than a lossy float.
    if isinstance(o, Decimal):
        return int(o) if o == o.to_integral_value() else str(o)
    raise TypeError(f"not JSON serialisable: {type(o).__name__}")


def _json(status: int, body: dict[str, Any], headers: dict[str, str] | None = None) -> dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json", "x-served-by-region": REGION, **(headers or {})},
        "body": json.dumps(body, default=_default),
    }


def _public(item: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in item.items() if k != "request_fingerprint"}
    out["amount"] = str(item["amount"])  # always a decimal string for clients
    return out


def _log(msg: str, **fields: Any) -> None:
    logger.info(json.dumps({"message": msg, "region": REGION, **fields}, default=str))


def create_order_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    try:
        body = json.loads(event.get("body") or "{}")
        item, created = orders.create_order(
            _table, REGION, headers.get("idempotency-key", ""), body.get("customer_id", ""), body.get("amount"))
    except json.JSONDecodeError:
        return _json(400, {"error": "body must be JSON"})
    except orders.OrderError as exc:
        return _json(exc.status, {"error": str(exc)})
    except (ClientError, BotoCoreError):
        logger.exception("create failed")
        return _json(503, {"error": "temporarily unavailable"}, {"retry-after": "1"})
    _log("order created" if created else "idempotent replay", pk=item["pk"])
    return _json(201 if created else 200, _public(item))


def update_status_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    order_id = (event.get("pathParameters") or {}).get("order_id", "")
    try:
        body = json.loads(event.get("body") or "{}")
        item = orders.update_status(_table, REGION, order_id, body.get("status", ""),
                                    int(body.get("expected_version", 0)))
    except (json.JSONDecodeError, ValueError):
        return _json(400, {"error": "body must be JSON with an integer expected_version"})
    except orders.WrongHomeRegion as exc:
        # The client (or an edge router) retries against the home Region.
        return _json(exc.status, {"error": str(exc)}, {"x-home-region": exc.home_region})
    except orders.OrderError as exc:
        return _json(exc.status, {"error": str(exc)})
    except (ClientError, BotoCoreError):
        logger.exception("update failed")
        return _json(503, {"error": "temporarily unavailable"}, {"retry-after": "1"})
    _log("status updated", pk=item["pk"], version=item["version"])
    return _json(200, _public(item))


def health_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Target for a Route 53 HTTPS health check.

    Returns 503 when the Region has been drained by an operator, or when a
    strongly consistent read of the canary item from the local replica fails.
    """
    if os.environ.get("REGION_DRAINED", "false").lower() == "true":
        return _json(503, {"healthy": False, "reason": "drained"})
    try:
        _health_table.get_item(Key=CANARY_KEY, ConsistentRead=True)
    except (ClientError, BotoCoreError) as exc:
        logger.warning(json.dumps({"message": "health check failed", "error": str(exc)}))
        return _json(503, {"healthy": False, "reason": "dynamodb"})
    return _json(200, {"healthy": True})
