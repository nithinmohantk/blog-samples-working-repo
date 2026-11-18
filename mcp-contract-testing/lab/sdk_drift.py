"""Run the same server file under several SDK installations and compare each contract with the
one from the newest installation. Nothing in server/app.py changes between runs; only the libraries underneath do.

    python lab/sdk_drift.py <output directory> label=/path/to/python [label=/path/to/python ...]
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "contract"))
from compat import as_dicts, compare  # noqa: E402
from snapshot import canonical, digest, stdio_target, take  # noqa: E402

APP = os.path.join(HERE, "..", "server", "app.py")


def versions(python: str) -> str:
    code = "import importlib.metadata as m; print('mcp', m.version('mcp'), 'pydantic', m.version('pydantic'))"
    return subprocess.run([python, "-c", code], capture_output=True, text=True, timeout=60).stdout.strip()


def why_not(python: str) -> str:
    """The last line the server prints when it cannot even be imported."""
    code = "import sys; sys.path.insert(0, sys.argv[1]); import app; app.build()"
    done = subprocess.run([python, "-c", code, os.path.dirname(APP)], capture_output=True, text=True, timeout=60)
    lines = [line for line in done.stderr.strip().splitlines() if line.strip()]
    return lines[-1][:200] if lines else "started when imported directly"


async def main(out: str, installs: list[str]) -> int:
    """The last installation listed is the one being upgraded to; every other one is compared with it."""
    os.makedirs(out, exist_ok=True)
    snapshots: dict[str, dict | None] = {}
    described: dict[str, str] = {}
    for install in installs:
        label, python = install.split("=", 1)
        described[label] = versions(python)
        try:
            snapshots[label] = await take(stdio_target(f"{python} {APP}"))
        except Exception as error:  # noqa: BLE001
            snapshots[label] = None
            described[label] += f"; did not start: {why_not(python)}"
            continue
        with open(os.path.join(out, f"contract-{label}.json"), "w", encoding="utf-8") as handle:
            handle.write(canonical(snapshots[label]))
    target_label = installs[-1].split("=", 1)[0]
    target = snapshots[target_label]
    rows = []
    for label, snapshot in snapshots.items():
        if snapshot is None:
            print(f"\n{label}: {described[label]}")
            rows.append({"label": label, "versions": described[label], "started": False})
            continue
        findings = [] if label == target_label else compare(snapshot, target)
        tally = {level: sum(f.level == level for f in findings) for level in ("breaking", "review", "compatible")}
        tools_same = snapshot["tools"] == target["tools"]
        rows.append({"label": label, "versions": described[label], "started": True, "sha256": digest(snapshot),
                     "protocolVersion": snapshot["protocolVersion"], "tools_identical_to_target": tools_same,
                     "upgrade_to": target_label, "tally": tally, "findings": as_dicts(findings)})
        print(f"\n{label}: {described[label]}: protocol {snapshot['protocolVersion']}, sha256 {digest(snapshot)[:12]}")
        if label != target_label:
            print(f"   upgrading to {target_label}: tool listing identical: {tools_same}; {tally}")
        for finding in findings:
            print(f"   {finding.level:<10} {finding.rule:<26} {finding.where}  {finding.detail[:90]}")
    with open(os.path.join(out, "sdk-drift.json"), "w", encoding="utf-8") as handle:
        json.dump(rows, handle, indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1], sys.argv[2:])))
