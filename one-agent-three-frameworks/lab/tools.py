"""The two tools every framework is given, as plain Python functions. One reads, one has a side effect."""
from __future__ import annotations

import asyncio
import threading
import time

ORDERS = {"A-100": {"status": "delivered", "total": 80.0}, "B-200": {"status": "shipped", "total": 35.5}}
LEDGER: list[dict] = []          # every tool execution, in the order it started
DELAY = 0.3                      # seconds a lookup takes: long enough to see whether two calls in one turn overlap
_lock = threading.Lock()


def reset() -> None:
    LEDGER.clear()


def _record(tool: str, **arguments) -> dict:
    entry = {"tool": tool, "arguments": arguments, "started": time.perf_counter(), "thread": threading.current_thread().name}
    with _lock:
        LEDGER.append(entry)
    return entry


def lookup_order(order_id: str) -> dict:
    """Looks up one order by its identifier and returns its status and total.

    Args:
        order_id: The order identifier, for example A-100.
    """
    entry = _record("lookup_order", order_id=order_id)
    time.sleep(DELAY)
    entry["finished"] = time.perf_counter()
    if order_id not in ORDERS:
        raise LookupError(f"order {order_id} not found in orders-db-internal-7.corp.example:5432")
    return {"order_id": order_id, **ORDERS[order_id]}


def refund_order(order_id: str, amount: float) -> dict:
    """Refunds part or all of an order to the customer. This moves money.

    Args:
        order_id: The order identifier, for example A-100.
        amount: The amount to refund, in euro.
    """
    entry = _record("refund_order", order_id=order_id, amount=amount)
    entry["finished"] = time.perf_counter()
    return {"order_id": order_id, "refunded": amount, "argument_type": type(amount).__name__}


async def lookup_order_async(order_id: str) -> dict:
    """Looks up one order by its identifier and returns its status and total.

    Args:
        order_id: The order identifier, for example A-100.
    """
    entry = _record("lookup_order_async", order_id=order_id)
    await asyncio.sleep(DELAY)
    entry["finished"] = time.perf_counter()
    return {"order_id": order_id, **ORDERS[order_id]}
