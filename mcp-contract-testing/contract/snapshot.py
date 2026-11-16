"""Take a contract snapshot of a running MCP server.

    python contract/snapshot.py --stdio "python server/app.py" --out contract/mcp-contract.json
    python contract/snapshot.py --url http://127.0.0.1:8765/mcp --out /tmp/live.json

The snapshot is everything a client can learn without calling a tool: server identity, protocol
version, capabilities, and the listings for tools, resources, resource templates and prompts.
Output is canonical JSON (sorted keys, entries sorted by name), so two snapshots of the same
contract are byte-identical and a text diff in a pull request is meaningful.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import shlex
import sys
from typing import Any, Awaitable, Callable

from mcp import Client, StdioServerParameters

FORMAT = 1
MAX_PAGES = 50  # a listing that never stops paginating must not hang the build
TOOL_FIELDS = ("name", "title", "description", "inputSchema", "outputSchema", "annotations")
RESOURCE_FIELDS = ("uri", "name", "title", "description", "mimeType")
TEMPLATE_FIELDS = ("uriTemplate", "name", "title", "description", "mimeType")
PROMPT_FIELDS = ("name", "title", "description", "arguments")


def plain(model: Any) -> dict[str, Any]:
    return model.model_dump(mode="json", by_alias=True, exclude_none=True)


def pick(entry: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    return {key: entry[key] for key in fields if key in entry}


async def every_page(call: Callable[..., Awaitable[Any]], attribute: str) -> list[dict[str, Any]]:
    entries, cursor = [], None
    for _ in range(MAX_PAGES):
        page = await call(cursor=cursor)
        entries.extend(plain(item) for item in getattr(page, attribute))
        cursor = getattr(page, "next_cursor", None)
        if not cursor:
            return entries
    raise RuntimeError(f"{attribute}: more than {MAX_PAGES} pages; refusing to continue")


async def take(target: StdioServerParameters | str, timeout: float = 30.0) -> dict[str, Any]:
    async with Client(target, read_timeout_seconds=timeout) as client:
        capabilities = plain(client.server_capabilities)
        if not capabilities.get("experimental"):
            capabilities.pop("experimental", None)  # 1.x SDKs send an empty object; it carries no promise
        info = plain(client.server_info) if client.server_info else {}
        snapshot: dict[str, Any] = {
            "contractFormat": FORMAT,
            "server": {"name": info.get("name"), "version": info.get("version")},
            "protocolVersion": client.protocol_version,
            "capabilities": capabilities,
            "instructions": client.instructions,
            "tools": [], "resources": [], "resourceTemplates": [], "prompts": [],
        }
        if "tools" in capabilities:
            tools = await every_page(client.list_tools, "tools")
            snapshot["tools"] = sorted((pick(t, TOOL_FIELDS) for t in tools), key=lambda t: t["name"])
        if "resources" in capabilities:
            resources = await every_page(client.list_resources, "resources")
            templates = await every_page(client.list_resource_templates, "resource_templates")
            snapshot["resources"] = sorted((pick(r, RESOURCE_FIELDS) for r in resources), key=lambda r: r["uri"])
            snapshot["resourceTemplates"] = sorted((pick(t, TEMPLATE_FIELDS) for t in templates), key=lambda t: t["uriTemplate"])
        if "prompts" in capabilities:
            prompts = await every_page(client.list_prompts, "prompts")
            snapshot["prompts"] = sorted((pick(p, PROMPT_FIELDS) for p in prompts), key=lambda p: p["name"])
        return snapshot


def canonical(snapshot: dict[str, Any]) -> str:
    return json.dumps(snapshot, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def digest(snapshot: dict[str, Any]) -> str:
    return hashlib.sha256(canonical(snapshot).encode()).hexdigest()


def stdio_target(command_line: str) -> StdioServerParameters:
    command, *arguments = shlex.split(command_line)
    return StdioServerParameters(command=command, args=arguments)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    where = parser.add_mutually_exclusive_group(required=True)
    where.add_argument("--stdio", help="command line that starts the server on stdio")
    where.add_argument("--url", help="Streamable HTTP endpoint of a running server")
    parser.add_argument("--out", help="file to write; standard output when omitted")
    parser.add_argument("--timeout", type=float, default=30.0)
    options = parser.parse_args()
    target = stdio_target(options.stdio) if options.stdio else options.url
    try:
        snapshot = asyncio.run(take(target, options.timeout))
    except Exception as error:  # noqa: BLE001  a build step needs one clear line, not a task-group traceback
        print(f"snapshot failed: {type(error).__name__}: {error}", file=sys.stderr)
        return 3
    text = canonical(snapshot)
    if options.out:
        with open(options.out, "w", encoding="utf-8") as handle:
            handle.write(text)
        print(f"{options.out}: {len(snapshot['tools'])} tools, {len(snapshot['resources'])} resources, "
              f"{len(snapshot['resourceTemplates'])} templates, {len(snapshot['prompts'])} prompts, sha256 {digest(snapshot)[:12]}", file=sys.stderr)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
