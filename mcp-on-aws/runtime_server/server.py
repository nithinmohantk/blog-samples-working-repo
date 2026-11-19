"""MCP server for Amazon Bedrock AgentCore Runtime (or any container host).

AgentCore Runtime expects a stateless Streamable HTTP MCP server listening on
0.0.0.0:8000 at the /mcp path. Built on the official MCP Python SDK, pinned
to mcp==1.26.0.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp.server.fastmcp import FastMCP  # noqa: E402
from mcp.server.fastmcp.exceptions import ToolError  # noqa: E402

import sales_tools  # noqa: E402

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
logger = logging.getLogger("sales-mcp")

mcp = FastMCP(
    "sales-data",
    host=os.environ.get("MCP_HOST", "0.0.0.0"),
    port=int(os.environ.get("MCP_PORT", "8000")),
    stateless_http=True,
)


def _call(fn, *args) -> dict[str, Any]:
    try:
        return fn(*args)
    except sales_tools.ToolInputError as exc:
        # Raised as a tool error, so the client receives isError=true
        # and the model can correct its arguments.
        raise ToolError(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - never leak internals to the model
        logger.exception("tool failed")
        raise ToolError("The tool failed. Try again later.") from exc


@mcp.tool()
def get_customer_summary(customer_id: str) -> dict[str, Any]:
    """Return the order count and total spend in EUR for one customer.

    customer_id: customer identifier in the form C-123456.
    """
    return _call(sales_tools.get_customer_summary, customer_id)


@mcp.tool()
def list_customer_orders(
    customer_id: str, limit: int = 10, next_token: str | None = None
) -> dict[str, Any]:
    """Return one page of a customer's orders, newest first (at most 25).

    Pass next_token from the previous result to get the next page.
    """
    return _call(sales_tools.list_customer_orders, customer_id, limit, next_token)


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
