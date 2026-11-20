"""Two ways to configure Microsoft Copilot SDK 2.0 (microsoft-copilot-sdk 2.0.1) for the same agent.

defaults:  what the README quick start shows. mode="coding-agent", PermissionHandler.approve_all,
           tools as plain handlers.
hardened:  mode="empty" with per-tenant storage and an explicit tool allow-list, a permission gate,
           a turn budget that aborts the session, tools wrapped with a timeout, a retry for transient
           errors, a result cap and a safe error, and a refund keyed on the business operation.
           For agents that must run generated code: the runtime sandbox, with the secret masked.

The model is reached through BYOK (an OpenAI-compatible endpoint), with Copilot inference off.
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from pydantic import BaseModel, Field

from copilot import RuntimeConnection, define_tool
from copilot._generated.rpc import SandboxConfig, SandboxCredentialsConfig, SandboxMaskedEnvVar
from copilot._mode import ToolSet
from copilot.rpc import PermissionDecisionApproveOnce, PermissionDecisionReject
from copilot.session import PermissionHandler
from copilot.session_events import PermissionRequestCustomTool, PermissionRequestShell
from copilot.tools import Tool, ToolInvocation, ToolResult

from .shop import Shop, Transient, as_text

log = logging.getLogger("harness")

REFUND = {"type": "object", "properties": {"order_id": {"type": "string"}, "amount": {"type": "number"}},
          "required": ["order_id", "amount"], "additionalProperties": False}

DESCRIPTIONS = {
    "get_order": "Look up an order, including customer notes",
    "get_tracking": "Look up shipping events for an order; the carrier API is unreliable",
    "export_history": "Export an order's full history",
    "check_stock": "Check stock for a product SKU",
    "refund": "Refund an amount on an order. Moves money.",
}


def byok(base_url: str) -> dict[str, Any]:
    return dict(github={"capi": {"enabled": False}},
                inference={"default_provider": "lab",
                           "providers": [{"name": "lab", "type": "openai", "base_url": base_url, "api_key": "unused"}]})


class OrderParams(BaseModel):
    order_id: str = Field(description="Order id, for example A-1")


class SkuParams(BaseModel):
    sku: str = Field(description="Product SKU")


class RefundParams(BaseModel):
    order_id: str
    amount: float


# ---- defaults ------------------------------------------------------------------------------

def default_tools(shop: Shop) -> list[Tool]:
    """As in the README: @define_tool with Pydantic parameters, handlers return plain values.
    Exceptions, sizes and delays reach the runtime unchanged."""
    @define_tool(name="get_order", description=DESCRIPTIONS["get_order"])
    async def get_order(p: OrderParams) -> str:
        return as_text(await shop.get_order(p.order_id))

    @define_tool(name="get_tracking", description=DESCRIPTIONS["get_tracking"])
    async def get_tracking(p: OrderParams) -> str:
        return as_text(await shop.get_tracking(p.order_id))

    @define_tool(name="export_history", description=DESCRIPTIONS["export_history"])
    async def export_history(p: OrderParams) -> str:
        return await shop.export_history(p.order_id)

    @define_tool(name="check_stock", description=DESCRIPTIONS["check_stock"])
    async def check_stock(p: SkuParams) -> str:
        return as_text(await shop.check_stock(p.sku))

    @define_tool(name="refund", description=DESCRIPTIONS["refund"])
    def refund(p: RefundParams, inv: ToolInvocation) -> str:
        # keyed on the call id only: a new call is a new payment
        return as_text(shop.refund(p.order_id, p.amount, inv.tool_call_id, inv.tool_call_id))

    return [get_order, get_tracking, export_history, check_stock, refund]


def defaults(shop: Shop, base_url: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """(client kwargs, session kwargs) as in the README quick start."""
    return ({"mode": "coding-agent"},
            dict(permissions={"on_request": PermissionHandler.approve_all},
                 tools={"definitions": default_tools(shop)}, **byok(base_url)))


# ---- hardened ------------------------------------------------------------------------------

RESULT_CAP = 4_000
TOOL_TIMEOUT_S = 1.0


async def guarded(name: str, call: Callable[[], Awaitable[Any]], *, retries: int = 2) -> ToolResult:
    """Timeout, retry with backoff and jitter for transient errors, a result cap, and a safe error."""
    for attempt in range(retries + 1):
        try:
            text = as_text(await asyncio.wait_for(call(), TOOL_TIMEOUT_S))
            if len(text) > RESULT_CAP:
                text = text[:RESULT_CAP] + f"... [cut at {RESULT_CAP} of {len(text)} characters; ask for a narrower range]"
            return ToolResult(text_result_for_llm=text, result_type="success")
        except asyncio.TimeoutError:
            return ToolResult(text_result_for_llm=f"{name} did not answer within {TOOL_TIMEOUT_S:.0f} s. "
                              "Tell the user it is unavailable; do not retry now.", result_type="timeout")
        except Transient:
            if attempt == retries:
                break
            await asyncio.sleep(0.05 * 2 ** attempt + random.uniform(0, 0.05))
        except Exception:
            break
    ref = uuid.uuid4().hex[:8]
    log.exception(json.dumps({"event": "tool_failed", "tool": name, "ref": ref}))
    return ToolResult(text_result_for_llm=f"{name} failed (reference {ref}). Do not retry; tell the user.",
                      result_type="failure")


def hardened_tools(shop: Shop) -> list[Tool]:
    @define_tool(name="get_order", description=DESCRIPTIONS["get_order"], idempotent=True)
    async def get_order(p: OrderParams) -> ToolResult:
        return await guarded("get_order", lambda: shop.get_order(p.order_id))

    @define_tool(name="get_tracking", description=DESCRIPTIONS["get_tracking"], idempotent=True)
    async def get_tracking(p: OrderParams) -> ToolResult:
        return await guarded("get_tracking", lambda: shop.get_tracking(p.order_id))

    @define_tool(name="export_history", description=DESCRIPTIONS["export_history"], idempotent=True)
    async def export_history(p: OrderParams) -> ToolResult:
        return await guarded("export_history", lambda: shop.export_history(p.order_id))

    @define_tool(name="check_stock", description=DESCRIPTIONS["check_stock"], idempotent=True)
    async def check_stock(p: SkuParams) -> ToolResult:
        return await guarded("check_stock", lambda: shop.check_stock(p.sku))

    @define_tool(name="refund", description=DESCRIPTIONS["refund"])
    def refund(p: RefundParams, inv: ToolInvocation) -> ToolResult:
        # The business key: one refund per order per conversation, whatever the call id.
        key = f"{inv.session_id}:{p.order_id}"
        return ToolResult(text_result_for_llm=as_text(shop.refund(p.order_id, p.amount, key, inv.tool_call_id)))

    return [get_order, get_tracking, export_history, check_stock, refund]


@dataclass
class Approver:
    """Writes need a decision the model does not control. Here: refunds only for orders the user named."""
    allowed_orders: set[str] = field(default_factory=set)
    decisions: list[tuple[str, str, bool]] = field(default_factory=list)

    def __call__(self, request: Any, _invocation: Any):
        match request:
            case PermissionRequestCustomTool(tool_name="refund", args=args):
                ok = (args or {}).get("order_id") in self.allowed_orders
                self.decisions.append(("refund", json.dumps(args), ok))
                if ok:
                    return PermissionDecisionApproveOnce()
                return PermissionDecisionReject(
                    feedback="Refunds need approval from a person; this one was not approved. Do not retry.")
            case PermissionRequestShell():
                self.decisions.append(("shell", getattr(request, "full_command_text", ""), False))
                return PermissionDecisionReject(feedback="This agent does not run commands.")
            case _:
                return PermissionDecisionApproveOnce()


@dataclass
class Budget:
    """Stops a session after max_turns model calls. The runtime has no turn limit for BYOK models,
    and send_and_wait's timeout only stops waiting, so the budget aborts the session itself."""
    max_turns: int = 12
    turns: int = 0
    stopped: bool = False

    def attach(self, session: Any) -> None:
        def on_event(event: Any) -> None:
            if getattr(event.type, "value", "") == "assistant.turn_start":
                self.turns += 1
                if self.turns > self.max_turns and not self.stopped:
                    self.stopped = True
                    asyncio.get_running_loop().create_task(session.abort())
        session.on(on_event)


def hardened(shop: Shop, base_url: str, tenant_dir: str, approver: Approver) -> tuple[dict[str, Any], dict[str, Any]]:
    client = {"mode": "empty", "runtime": RuntimeConnection.for_default(base_directory=tenant_dir)}
    session = dict(permissions={"on_request": approver},
                   tools={"definitions": hardened_tools(shop), "available_tools": ToolSet().add_custom("*"),
                          "large_output": {"output_directory": tenant_dir}},
                   **byok(base_url))
    return client, session


def sandboxed_code(base_url: str, secret_env: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """For an agent that must run generated code: the bash tool inside the runtime sandbox
    (Linux: bubblewrap, slirp4netns and ip on PATH), with the secret masked."""
    sandbox = SandboxConfig(enabled=True, credentials=SandboxCredentialsConfig(
        env_vars={secret_env: SandboxMaskedEnvVar(inject_hosts=["payments.example.com"])}))
    return ({"mode": "coding-agent"},
            dict(permissions={"on_request": PermissionHandler.approve_all, "sandbox": sandbox}, **byok(base_url)))
