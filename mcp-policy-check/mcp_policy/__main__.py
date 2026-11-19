"""python -m mcp_policy managed-settings.json [inventory.json]

Lints a Claude Code managed MCP policy and, given an inventory of servers
found on developer machines (for example exported from Defender's MCP
discovery), shows which would load. Exit code 2 when a high finding exists.
"""
from __future__ import annotations

import json
import sys

from .lint import lint
from .model import Policy, Server, evaluate


def main(argv: list[str]) -> int:
    managed = json.loads(open(argv[0], encoding="utf-8").read())
    findings = lint(managed)
    for f in findings:
        print(f"[{f.level.upper():6}] {f.code}: {f.message}")
    if len(argv) > 1:
        inventory = json.loads(open(argv[1], encoding="utf-8").read())
        policy = Policy.from_scopes(managed, [])
        print()
        for item in inventory:
            s = Server(item["name"], url=item.get("url"),
                       command=tuple(item["command"]) if item.get("command") else None,
                       source=item.get("source", "user"))
            d = evaluate(policy, s)
            target = s.url or " ".join(s.command or ())
            print(f"{'LOAD ' if d.allowed else 'BLOCK'} {s.name:<14} {target:<52} {d.reason}")
    return 2 if any(f.level == "high" for f in findings) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
