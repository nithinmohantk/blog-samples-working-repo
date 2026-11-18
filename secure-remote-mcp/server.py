"""
server.py - a remote MCP server acting as an OAuth 2.1 resource server.
Stateless streamable HTTP on 0.0.0.0:8000/mcp, so it runs unchanged on AgentCore Runtime,
Lambda Web Adapter, ECS, Azure Container Apps or an Azure Functions custom handler.
"""
import os
import re

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from token_verifier import JwksTokenVerifier

ISSUER = os.environ["MCP_ISSUER"]                    # e.g. https://login.microsoftonline.com/<tenant>/v2.0
JWKS_URI = os.environ["MCP_JWKS_URI"]
RESOURCE_URL = os.environ["MCP_RESOURCE_URL"]        # the public URL clients use, e.g. https://mcp.example.com/mcp
AUDIENCES = os.environ.get("MCP_AUDIENCES", RESOURCE_URL).split(",")
ALLOWED_HOSTS = os.environ["MCP_ALLOWED_HOSTS"].split(",")           # e.g. mcp.example.com
ALLOWED_ORIGINS = [o for o in os.environ.get("MCP_ALLOWED_ORIGINS", "").split(",") if o]

READ, WRITE = "orders.read", "orders.write"
ORDER_ID = re.compile(r"ORD-\d{3,10}")

mcp = FastMCP(
    "orders",
    host="0.0.0.0",
    port=8000,
    stateless_http=True,          # no session affinity: any instance can serve any request
    json_response=True,           # plain JSON replies; friendlier to gateways that buffer
    token_verifier=JwksTokenVerifier(ISSUER, AUDIENCES, JWKS_URI),
    auth=AuthSettings(
        issuer_url=ISSUER,                    # advertised in the protected resource metadata
        resource_server_url=RESOURCE_URL,
        required_scopes=[READ],               # enforced on every HTTP request, before any MCP code runs
    ),
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=ALLOWED_HOSTS,
        allowed_origins=ALLOWED_ORIGINS,
    ),
)


def _require(scope: str) -> str:
    """Per-tool authorization. Returns the caller's subject for the audit trail."""
    token = get_access_token()
    if token is None or scope not in token.scopes:
        raise PermissionError(f"This tool requires the '{scope}' scope.")
    return token.subject or token.client_id


def _order_id(value: str) -> str:
    if not ORDER_ID.fullmatch(value):
        raise ValueError("order_id must look like ORD-10042")
    return value


@mcp.tool()
def get_order_status(order_id: str) -> dict:
    """Return the fulfilment status of one order. order_id looks like ORD-10042."""
    _require(READ)
    return {"order_id": _order_id(order_id), "status": "SHIPPED"}


@mcp.tool()
def cancel_order(order_id: str) -> dict:
    """Cancel one order. Irreversible. order_id looks like ORD-10042."""
    subject = _require(WRITE)
    # Downstream calls use this server's own credential, never the caller's token.
    return {"order_id": _order_id(order_id), "status": "CANCELLED", "cancelled_by": subject}


app = mcp.streamable_http_app()

if __name__ == "__main__":
    mcp.run(transport="streamable-http")
