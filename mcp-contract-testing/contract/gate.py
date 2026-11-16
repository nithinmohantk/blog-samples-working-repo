"""The build gate: compare a contract snapshot with the one on the base branch and decide.

    python contract/gate.py --base base.json --head contract/mcp-contract.json [--live live.json]

Exit codes:
  0  no breaking change, or every breaking change is covered by a major version bump
  1  breaking change without a major version bump
  2  the committed snapshot does not match the running server (regenerate it and commit)
  3  a snapshot could not be read

`review` findings never fail the build on their own. They are printed, and written to the job
summary when GITHUB_STEP_SUMMARY is set, so that the pull request shows a person what to read.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from compat import Finding, compare, worst  # noqa: E402


def load(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def major(version: str | None) -> int | None:
    match = re.match(r"^v?(\d+)\.", version or "")
    return int(match.group(1)) if match else None


def report(findings: list[Finding]) -> str:
    if not findings:
        return "No contract changes.\n"
    lines = ["| Level | Where | Rule | Detail |", "| --- | --- | --- | --- |"]
    lines += [f"| {f.level} | `{f.where}` | {f.rule} | {f.detail.replace('|', '/')} |" for f in findings]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", required=True, help="snapshot from the base branch")
    parser.add_argument("--head", required=True, help="snapshot committed on this branch")
    parser.add_argument("--live", help="snapshot just taken from the running server")
    parser.add_argument("--json", help="write the findings to this file")
    options = parser.parse_args()
    try:
        base, head = load(options.base), load(options.head)
        live = load(options.live) if options.live else None
    except (OSError, json.JSONDecodeError) as error:
        print(f"cannot read snapshot: {error}", file=sys.stderr)
        return 3

    if live is not None and live != head:
        drift = compare(head, live)
        print("STALE SNAPSHOT: the running server no longer matches the committed contract.")
        print(report(drift) if drift else "The difference is outside the compared fields; regenerate the snapshot.\n")
        print("Run contract/snapshot.py, commit the result, and let the reviewer see the diff.")
        return 2

    findings = compare(base, head)
    text = report(findings)
    print(text)
    if options.json:
        with open(options.json, "w", encoding="utf-8") as handle:
            json.dump([f.__dict__ for f in findings], handle, indent=2)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write("## MCP contract\n\n" + text)

    if worst(findings) != "breaking":
        print(f"PASS: {sum(f.level == 'review' for f in findings)} change(s) to review, none breaking.")
        return 0
    was, now = major(base["server"].get("version")), major(head["server"].get("version"))
    if was is not None and now is not None and now > was:
        print(f"PASS: breaking changes are covered by the major version bump {base['server']['version']} -> {head['server']['version']}.")
        return 0
    print(f"FAIL: breaking change without a major version bump (server version {base['server'].get('version')} -> {head['server'].get('version')}).")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
