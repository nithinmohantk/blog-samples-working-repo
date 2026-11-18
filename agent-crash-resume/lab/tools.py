"""Three tools with side effects, and a ledger that records every effect.

The ledger is an append-only file standing in for the outside world: the warehouse, the payment
provider and the mail service. A line of kind "effect" is something that really happened and cannot be
taken back. The lab counts those lines after a crash and a resume, and a tool that appears twice was
done twice.

Two versions of each tool exist. The plain ones act every time they are called. The idempotent ones
derive a key from the business identifiers in their arguments, look it up, and return the recorded
result if the work was already done. The key deliberately ignores the tool call id: a model that is
asked again issues a new call id for the same intent.

The crash point is set by the lab through CRASH_AT. A tool that reaches it writes a marker file and
then waits to be killed.
"""
from __future__ import annotations

import json
import os
import time

LEDGER = os.environ.get("LAB_LEDGER", "ledger.jsonl")
MARKER = os.environ.get("LAB_MARKER", "crash.marker")
CRASH_AT = os.environ.get("CRASH_AT", "")  # "<tool>:before" or "<tool>:after"
IDEMPOTENT = os.environ.get("LAB_TOOLS", "plain") == "idempotent"


def record(kind: str, tool: str, key: str, result: dict) -> None:
    with open(LEDGER, "a", encoding="utf-8") as handle:
        handle.write(json.dumps({"kind": kind, "tool": tool, "key": key, "result": result, "pid": os.getpid()}) + "\n")
        handle.flush()
        os.fsync(handle.fileno())  # the effect has to be on disk before the process can be killed


def recorded(key: str) -> dict | None:
    if not os.path.exists(LEDGER):
        return None
    with open(LEDGER, encoding="utf-8") as handle:
        for line in handle:
            entry = json.loads(line)
            if entry["kind"] == "effect" and entry["key"] == key:
                return entry["result"]
    return None


def crash_point(tool: str, moment: str) -> None:
    if CRASH_AT == f"{tool}:{moment}":
        with open(MARKER, "w", encoding="utf-8") as handle:
            handle.write(CRASH_AT)
        time.sleep(120)  # the lab sends SIGKILL long before this ends


def act(tool: str, key: str, result: dict) -> dict:
    """Do the work of a tool exactly as the selected version would."""
    crash_point(tool, "before")
    if IDEMPOTENT:
        earlier = recorded(key)
        if earlier is not None:
            record("replayed", tool, key, earlier)  # asked again, nothing done again
            return earlier
    record("effect", tool, key, result)
    crash_point(tool, "after")  # the effect exists, and the framework has not been told
    return result


def reserve_stock(order_id: str, sku: str, quantity: int) -> dict:
    """Reserve stock for an order."""
    return act("reserve_stock", f"reserve:{order_id}:{sku}", {"order_id": order_id, "sku": sku, "reserved": quantity})


def charge_card(order_id: str, amount_cents: int) -> dict:
    """Charge the customer's card for an order."""
    return act("charge_card", f"charge:{order_id}", {"order_id": order_id, "charged_cents": amount_cents, "status": "captured"})


def send_confirmation(order_id: str, email: str) -> dict:
    """Send the order confirmation email."""
    return act("send_confirmation", f"confirm:{order_id}", {"order_id": order_id, "sent_to": email})


TOOLS = [reserve_stock, charge_card, send_confirmation]
TASK = "Place order O-1001: 3 of FAS-0012 for 37.50 euro, confirmation to buyer@example.com."
INSTRUCTIONS = "You place orders. Reserve the stock, charge the card, then send the confirmation. Be brief."
