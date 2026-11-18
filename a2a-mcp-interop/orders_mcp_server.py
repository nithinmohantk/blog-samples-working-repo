"""orders_mcp_server.py - one tool over streamable HTTP, laid out for the AgentCore MCP contract."""
import re

from mcp.server.fastmcp import FastMCP

ORDER_ID = re.compile(r"\bORD-\d{3,10}\b")

# stateless_http=True: no session affinity is assumed, so any instance can serve any request.
mcp = FastMCP("orders", host="0.0.0.0", port=8000, stateless_http=True)


def lookup_order(order_id: str) -> dict:
    """Replace with a real lookup. Validate and authorise here: the caller is another system's agent."""
    if not ORDER_ID.fullmatch(order_id):
        raise ValueError("order_id must look like ORD-10042")
    return {"order_id": order_id, "status": "SHIPPED", "carrier": "An Post"}


@mcp.tool()
def get_order_status(order_id: str) -> dict:
    """Return the fulfilment status of one order. order_id looks like ORD-10042."""
    return lookup_order(order_id)      # a ValueError is reported to the caller as a tool error


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
