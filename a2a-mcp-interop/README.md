# A2A + MCP interop sample

Companion code for "A2A and MCP Across Clouds" (dataa.dev, 7 July 2026).

| File | Role |
| --- | --- |
| `orders_mcp_server.py` | MCP tool server (AgentCore MCP contract: 0.0.0.0:8000, `/mcp`, stateless) |
| `order_agent.py` | Agent step; calls the tool over MCP |
| `order_agent_a2a.py` | A2A server (AgentCore A2A contract: 0.0.0.0:9000, JSON-RPC on `/`), A2A 1.0 + 0.3 |
| `test_a2a.py` | Sends the same question in both wire formats and checks the version-skew error |
| `dotnet/OrderAgentClient.cs` | Agent Framework client. NOT compiled by the author - see below |

## Run

    python -m venv .venv && .venv\Scripts\activate
    pip install -r requirements.txt
    python orders_mcp_server.py        # terminal 1
    python test_a2a.py                 # terminal 2 -> ALL A2A TESTS OK

Tested with Python 3.13, a2a-sdk 1.1.0, mcp 1.28.1, starlette 1.10.0.

## Not verified

* Nothing here was deployed to a live AgentCore runtime. In particular, confirm the
  `A2A-Version` request header reaches the container (see the runtime header allowlist).
* `dotnet/OrderAgentClient.cs` was written against the public source of `A2A` and
  `Microsoft.Agents.AI.A2A` but not compiled. Both were preview packages in July 2026.
  Build it and adjust to the package versions you pin.
