"""Scenario 11 worker. Phase A pays a refund and the process dies before the result is recorded.
Phase B resumes the same session from disk and asks the agent to continue.

    python -m harness.crash_worker A|B <session_id> <base_url> <ledger.db> <defaults|hardened> <work_dir>
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

from copilot import CopilotClient, RuntimeConnection
from copilot._mode import ToolSet
from copilot.session import PermissionHandler
from copilot.tools import Tool, ToolInvocation, ToolResult

from .configs import REFUND, Approver, byok
from .shop import Shop, as_text

phase, sid, base_url, ledger, config, work = sys.argv[1:7]
shop = Shop(ledger_path=ledger)


def refund(inv: ToolInvocation) -> ToolResult:
    a = inv.arguments
    key = inv.tool_call_id if config == "defaults" else f"{inv.session_id}:{a['order_id']}"
    result = shop.refund(a["order_id"], a["amount"], key, inv.tool_call_id)
    if phase == "A":
        os._exit(1)  # the money has moved; the result never reaches the runtime
    return ToolResult(text_result_for_llm=as_text(result))


async def main() -> None:
    tool = Tool(name="refund", description="Refund an amount on an order. Moves money.", parameters=REFUND, handler=refund)
    perms = ({"on_request": PermissionHandler.approve_all} if config == "defaults"
             else {"on_request": Approver(allowed_orders={"A-1"})})
    session_kw = dict(model="crashy", permissions=perms, **byok(base_url),
                      tools={"definitions": [tool], "available_tools": ToolSet().add_custom("*")})
    # Both phases share the tenant directory, which holds the session journal.
    async with CopilotClient(mode="empty", runtime=RuntimeConnection.for_default(base_directory=work)) as client:
        if phase == "A":
            s = await client.create_session(session_id=sid, **session_kw)
            await s.send_and_wait("Refund 25.00 on order A-1; the customer returned it.", timeout=60)
        else:
            s = await client.resume_session(sid, **session_kw)
            await s.send_and_wait("Continue where you left off.", timeout=60)
    print(json.dumps({"refunds_paid": shop.refunds(), "ledger_rows": len(shop.refunds())}))


asyncio.run(main())
