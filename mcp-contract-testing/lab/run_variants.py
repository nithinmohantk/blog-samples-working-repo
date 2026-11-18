"""For every variant: snapshot it, ask the gate, and replay the recorded calls against it.

    python lab/run_variants.py <output directory>
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "contract"))
sys.path.insert(0, HERE)
from compat import as_dicts, compare, worst  # noqa: E402
from replay import replay  # noqa: E402
from snapshot import digest, stdio_target, take  # noqa: E402
from variants import VARIANTS  # noqa: E402


def server(key: str):
    return stdio_target(f"{sys.executable} {os.path.join(HERE, 'variants.py')} {key}")


async def main(out: str) -> int:
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(HERE, "..", "contract", "mcp-contract.json"), encoding="utf-8") as handle:
        baseline = json.load(handle)
    with open(os.path.join(HERE, "..", "contract", "calls.json"), encoding="utf-8") as handle:
        calls = json.load(handle)["calls"]
    live = await take(server("baseline"))
    print(f"baseline  sha256 {digest(live)[:12]}  matches the committed contract: {live == baseline}")
    rows = []
    print(f"\n{'id':<4} {'gate':<11} {'replay':<8} change")
    for key, (change, _) in VARIANTS.items():
        started = time.perf_counter()
        snapshot = await take(server(key))
        findings = compare(baseline, snapshot)
        replayed = await replay(server(key), baseline, calls)
        different = [r for r in replayed if not r["as_recorded"]]
        level = worst(findings) or "none"
        rows.append({"id": key, "change": change, "gate": level, "rules": sorted({f.rule for f in findings if f.level == level}),
                     "findings": as_dicts(findings), "replay_different": len(different), "replay_total": len(replayed),
                     "replay": different, "seconds": round(time.perf_counter() - started, 2)})
        print(f"{key:<4} {level:<11} {len(different)} of {len(replayed):<3} {change}")
        for finding in findings:
            if finding.level == level:
                print(f"       {finding.rule}: {finding.where}  {finding.detail[:110]}")
        for row in different:
            print(f"       replay {row['id']}: expected {row['expected']}, got {row['outcome']}  {row['detail'][:100]}")
    with open(os.path.join(out, "variants.json"), "w", encoding="utf-8") as handle:
        json.dump(rows, handle, indent=2)
    tally = {level: sum(r["gate"] == level for r in rows) for level in ("breaking", "review", "compatible", "none")}
    silent = [r["id"] for r in rows if r["gate"] == "breaking" and r["replay_different"] == 0]
    loud = [r["id"] for r in rows if r["gate"] != "breaking" and r["replay_different"] > 0]
    print(f"\n{len(rows)} variants: {tally}")
    print(f"flagged breaking by the gate, with every recorded call still behaving as recorded: {silent}")
    print(f"not flagged breaking, yet a recorded call behaved differently: {loud}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1])))
