"""Start an MCP server on stdio and read its tool listing. No tool is ever called."""
from __future__ import annotations

import os
import time
from typing import Any

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

MAX_PAGES = 50


async def read_listing(command: list[str], env: dict[str, str] | None = None, timeout: float = 60.0) -> dict[str, Any]:
    """Returns the server's name and version, its tools as plain dictionaries, and how long the listing took."""
    parameters = StdioServerParameters(command=command[0], args=command[1:], env={**os.environ, **(env or {})})
    with open(os.devnull, "w") as quiet, anyio.fail_after(timeout):
        async with stdio_client(parameters, errlog=quiet) as (read, write):
            async with ClientSession(read, write) as session:
                started = time.perf_counter()
                init = await session.initialize()
                tools, cursor = [], None
                for _ in range(MAX_PAGES):
                    page = await session.list_tools(cursor)
                    tools += [tool.model_dump(mode="json", by_alias=True, exclude_none=True) for tool in page.tools]
                    cursor = page.nextCursor
                    if not cursor:
                        break
                return {"server": init.serverInfo.name, "version": init.serverInfo.version, "protocol": init.protocolVersion,
                        "instructions": init.instructions or "", "tools": tools, "seconds": round(time.perf_counter() - started, 2)}
