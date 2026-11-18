"""A guarded MCP client session: limits, pins and scans between the server and whatever reads its output.

    guarded = GuardedSession(session, "orders", PinStore("pins.json"))
    tools = await guarded.list_tools()            # raises Blocked if the listing is over a limit
    result = await guarded.call_tool("add", {...})  # raises Blocked if the tool is not the one that was approved

It wraps mcp.ClientSession and changes nothing on the wire. Everything it refuses, it refuses on the
client side, which is the only side a client can trust.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import mcp.types as types
from mcp import ClientSession

from .pins import PinStore, Verdict
from .scan import Finding, scan_listing, scan_result


class Blocked(Exception):
    """The guard refused to pass something on. The message says which rule and why."""


@dataclass(frozen=True)
class Limits:
    max_pages: int = 20
    max_tools: int = 200
    max_description_chars: int = 4000
    max_listing_chars: int = 200_000
    max_result_chars: int = 100_000


class GuardedSession:
    def __init__(self, session: ClientSession, server: str, pins: PinStore, limits: Limits = Limits(),
                 verify_before_call: bool = True, known_tools: frozenset[str] = frozenset()) -> None:
        self.session, self.server, self.pins, self.limits = session, server, pins, limits
        self.verify_before_call = verify_before_call
        self.known_tools = known_tools  # tool names on the user's other servers, for cross-server checks
        self.listing_stale = True       # set again by on_message when the server says its tools changed
        self.tools: list[dict[str, Any]] = []

    async def on_message(self, message: Any) -> None:
        """Pass this as ClientSession(message_handler=...) so that a list_changed notification is not lost."""
        if isinstance(getattr(message, "root", None), types.ToolListChangedNotification):
            self.listing_stale = True

    async def list_tools(self) -> list[dict[str, Any]]:
        tools, cursor, size = [], None, 0
        for _ in range(self.limits.max_pages):
            page = await self.session.list_tools(cursor)
            for tool in page.tools:
                plain = tool.model_dump(mode="json", by_alias=True, exclude_none=True)
                if len(plain.get("description") or "") > self.limits.max_description_chars:
                    raise Blocked(f"limit: description of {tool.name} is {len(plain['description'])} characters")
                size += len(str(plain))
                tools.append(plain)
            if len(tools) > self.limits.max_tools:
                raise Blocked(f"limit: more than {self.limits.max_tools} tools")
            if size > self.limits.max_listing_chars:
                raise Blocked(f"limit: listing is larger than {self.limits.max_listing_chars} characters")
            cursor = page.nextCursor
            if not cursor:
                self.tools, self.listing_stale = tools, False
                return tools
        raise Blocked(f"limit: listing did not end within {self.limits.max_pages} pages")

    def scan(self, instructions: str | None = None) -> list[Finding]:
        return scan_listing(self.tools, instructions, self.known_tools)

    def verify(self) -> Verdict:
        return self.pins.verify(self.server, self.tools)

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> types.CallToolResult:
        if self.verify_before_call or self.listing_stale:
            await self.list_tools()  # one extra round trip; a silent change cannot be seen any other way
        verdict = self.verify()
        if name in verdict.changed:
            raise Blocked(f"pin: the definition of {name} has changed since it was approved")
        if name in verdict.unapproved or name not in verdict.unchanged:
            raise Blocked(f"pin: {name} has not been approved")
        result = await self.session.call_tool(name, arguments or {})
        text = "".join(block.text for block in result.content if isinstance(block, types.TextContent))
        if len(text) > self.limits.max_result_chars:
            raise Blocked(f"limit: result of {name} is {len(text)} characters")
        suspicious = scan_result(text, {tool["name"] for tool in self.tools} | self.known_tools)
        if suspicious:
            raise Blocked(f"result: {name} returned text that addresses the model ({suspicious[0].rule}: {suspicious[0].evidence})")
        return result
