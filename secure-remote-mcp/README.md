# Secure remote MCP server sample

Companion code for "Hosting Remote MCP Servers Securely on AWS and Azure" (dataa.dev, 14 July 2026).

| File | Role |
| --- | --- |
| `token_verifier.py` | JWT validation: pinned algorithm, issuer, audience, expiry, JWKS with rotation |
| `server.py` | Stateless streamable-HTTP MCP server acting as an OAuth resource server; per-tool scopes |
| `test_server.py` | Starts a throwaway issuer and the server, then runs 13 positive and negative checks |
| `dotnet/Program.cs` | The same rules in ASP.NET Core with Entra ID. NOT compiled by the author |

## Run

    python -m venv .venv && .venv\Scripts\activate
    pip install -r requirements.txt
    python test_server.py            # -> ALL MCP AUTH TESTS OK

Tested with Python 3.13, mcp 1.28.1, PyJWT 2.15.1. Ports 8000 and 9100 must be free.

## Configuration (server.py)

| Variable | Example |
| --- | --- |
| `MCP_ISSUER` | `https://login.microsoftonline.com/<tenant>/v2.0` |
| `MCP_JWKS_URI` | `https://login.microsoftonline.com/<tenant>/discovery/v2.0/keys` |
| `MCP_RESOURCE_URL` | `https://mcp.example.com/mcp` |
| `MCP_AUDIENCES` | comma-separated accepted `aud` values; defaults to the resource URL |
| `MCP_ALLOWED_HOSTS` | `mcp.example.com` |
| `MCP_ALLOWED_ORIGINS` | optional, for browser-based clients |

## Not verified

* Not deployed to AWS or Azure. Behaviour behind AgentCore Runtime, API Gateway, API Management
  or App Service authentication was taken from vendor documentation, not measured.
* `dotnet/Program.cs` was not compiled. Build it and adjust to the package version you pin.
