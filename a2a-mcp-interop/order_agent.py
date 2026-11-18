"""
order_agent.py
The agent's reasoning step, kept free of A2A types. It reaches its tool through MCP,
so the tool can be owned, deployed and secured by a different team.
A production agent would hand the tool list to a model; the control flow here is fixed
so the sample runs without model credentials.
"""
import json
import os
import re

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

ORDERS_MCP_URL = os.environ.get("ORDERS_MCP_URL", "http://localhost:8000/mcp")
ORDER_ID = re.compile(r"\bORD-\d{3,10}\b")


async def answer(question: str) -> str:
    match = ORDER_ID.search(question or "")
    if not match:
        return "I can only help with order status. Include an order number such as ORD-10042."

    async with streamablehttp_client(ORDERS_MCP_URL) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("get_order_status", {"order_id": match.group()})

    if result.isError:
        return "The order system could not answer that request."
    order = json.loads(result.content[0].text)
    return f"Order {order['order_id']} has status {order['status']} with carrier {order['carrier']}."
