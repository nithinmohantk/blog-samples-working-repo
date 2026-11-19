"""End-to-end test: start the MCP server over Streamable HTTP and call it with
the official MCP Python client, the same way an AgentCore Runtime client would
reach it on 0.0.0.0:8000/mcp."""

import asyncio
import json
import socket
import threading
import time

import uvicorn
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from conftest import expected_total


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start(app, port):
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            return server, thread
        time.sleep(0.05)
    raise RuntimeError("server did not start")


async def _exercise(url):
    async with streamable_http_client(url) as (read, write, _):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            tools = await session.list_tools()
            summary = await session.call_tool("get_customer_summary", {"customer_id": "C-000002"})
            bad = await session.call_tool("get_customer_summary", {"customer_id": "x"})
            page = await session.call_tool("list_customer_orders", {"customer_id": "C-000001", "limit": 3})
            return init, tools, summary, bad, page


def test_streamable_http_round_trip(orders_table):
    from runtime_server.server import mcp

    port = _free_port()
    server, thread = _start(mcp.streamable_http_app(), port)
    try:
        init, tools, summary, bad, page = asyncio.run(_exercise(f"http://127.0.0.1:{port}/mcp"))
    finally:
        server.should_exit = True
        thread.join(timeout=5)

    print("negotiated protocol version:", init.protocolVersion)
    names = sorted(t.name for t in tools.tools)
    assert names == ["get_customer_summary", "list_customer_orders"]
    schema = next(t for t in tools.tools if t.name == "list_customer_orders").inputSchema
    assert schema["required"] == ["customer_id"]

    assert summary.isError is False
    body = summary.structuredContent or json.loads(summary.content[0].text)
    assert body["order_count"] == 2
    assert body["total_spend"] == expected_total("C-000002")

    assert bad.isError is True
    assert "C-123456" in bad.content[0].text

    page_body = page.structuredContent or json.loads(page.content[0].text)
    assert [o["order_id"] for o in page_body["orders"]] == ["O-0029", "O-0028", "O-0027"]
    assert page_body["next_token"]
