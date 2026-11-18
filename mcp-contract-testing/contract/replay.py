"""Replay recorded calls against a running MCP server and check them against the contract.

    python contract/replay.py --stdio "python server/app.py" --contract contract/mcp-contract.json

The listing says what a server promises. This checks that it keeps the promise: each recorded
call must end the way it was recorded (a result, or a tool error), and each successful result's
structuredContent must validate against the output schema in the committed snapshot. Validating
against the snapshot, not against the live listing, is the point: a server that changes its
output and its schema together still agrees with itself.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from typing import Any

from jsonschema import Draft202012Validator
from mcp import Client, MCPError, StdioServerParameters

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from snapshot import stdio_target  # noqa: E402


def first_text(result: Any) -> str:
    for block in result.content or []:
        if getattr(block, "type", "") == "text":
            return " ".join(block.text.split())[:160]
    return ""


async def replay(target: StdioServerParameters | str, contract: dict[str, Any], calls: list[dict[str, Any]],
                 timeout: float = 30.0) -> list[dict[str, Any]]:
    schemas = {tool["name"]: tool.get("outputSchema") for tool in contract["tools"]}
    rows: list[dict[str, Any]] = []
    async with Client(target, read_timeout_seconds=timeout) as client:
        for call in calls:
            row = {"id": call["id"], "tool": call["tool"], "expected": call["expect"], "detail": ""}
            try:
                result = await client.call_tool(call["tool"], call["arguments"])
            except MCPError as error:  # the protocol refused the request: unknown tool, bad params
                row.update(outcome="protocol-error", detail=" ".join(str(error).split())[:160])
            except Exception as error:  # noqa: BLE001  the SDK's own client-side validation, a dropped connection
                row.update(outcome="client-error", detail=f"{type(error).__name__}: {' '.join(str(error).split())[:140]}")
            else:
                if result.is_error:
                    row.update(outcome="tool-error", detail=first_text(result))
                else:
                    row["outcome"] = "ok"
                    schema = schemas.get(call["tool"])
                    if schema is not None:
                        problems = sorted(Draft202012Validator(schema).iter_errors(result.structured_content), key=lambda e: list(e.path))
                        if problems:
                            where = "/".join(str(p) for p in problems[0].path) or "(root)"
                            row.update(outcome="contract-violation", detail=f"{where}: {problems[0].message[:120]}")
            row["as_recorded"] = row["outcome"] == call["expect"]
            rows.append(row)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    where = parser.add_mutually_exclusive_group(required=True)
    where.add_argument("--stdio")
    where.add_argument("--url")
    parser.add_argument("--contract", required=True)
    parser.add_argument("--calls", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "calls.json"))
    parser.add_argument("--json")
    options = parser.parse_args()
    with open(options.contract, encoding="utf-8") as handle:
        contract = json.load(handle)
    with open(options.calls, encoding="utf-8") as handle:
        calls = json.load(handle)["calls"]
    target = stdio_target(options.stdio) if options.stdio else options.url
    rows = asyncio.run(replay(target, contract, calls))
    for row in rows:
        print(f"{'ok  ' if row['as_recorded'] else 'DIFF'}  {row['id']:<20} expected {row['expected']:<10} got {row['outcome']:<18} {row['detail']}")
    if options.json:
        with open(options.json, "w", encoding="utf-8") as handle:
            json.dump(rows, handle, indent=2)
    failed = [row for row in rows if not row["as_recorded"]]
    print(f"{len(rows) - len(failed)} of {len(rows)} calls behaved as recorded")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
