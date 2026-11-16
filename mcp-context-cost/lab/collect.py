"""Start every server in servers.json, read its tool listing, and write them all to one file.

    python lab/collect.py <output directory> --node <dir with node_modules> --bin <venv bin dir> [--github-binary <path> --github-version <tag>]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from measure.listing import read_listing  # noqa: E402


def npm_command(node: Path, package: str) -> list[str]:
    """The command a package's own bin entry would run, without going through npx or a shell."""
    root = node / "node_modules" / package
    manifest = json.loads((root / "package.json").read_text(encoding="utf-8"))
    entry = manifest["bin"] if isinstance(manifest["bin"], str) else next(iter(manifest["bin"].values()))
    return ["node", str(root / entry)]


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("out")
    parser.add_argument("--node", required=True)
    parser.add_argument("--bin", required=True)
    parser.add_argument("--github-binary", default="")
    parser.add_argument("--github-version", default="")
    options = parser.parse_args()
    servers = json.loads((HERE.parent / "servers.json").read_text(encoding="utf-8"))["servers"]
    collected = []
    with tempfile.TemporaryDirectory() as work:
        subprocess.run(["git", "init", "-q", work], check=True)  # the git and filesystem servers need a place to point at
        print(f"{'server':<20} {'package':<50} {'version':<12} {'tools':>5}  {'listing':>8}")
        for spec in servers:
            arguments = [a.replace("{work}", work) for a in spec["arguments"]]
            version = spec["version"]
            try:
                if spec["source"] == "npm":
                    command = npm_command(Path(options.node), spec["package"]) + arguments
                elif spec["source"] == "pypi":
                    command = [os.path.join(options.bin, spec["executable"])] + arguments
                else:
                    if not options.github_binary:
                        raise FileNotFoundError("no release binary was downloaded")
                    command, version = [options.github_binary] + arguments, options.github_version
                listing = await read_listing(command, spec.get("env"))
            except Exception as error:  # noqa: BLE001  one server failing to start must not lose the others
                reason = f"{type(error).__name__}: {' '.join(str(error).split())[:120]}"
                print(f"{spec['name']:<20} {spec['package']:<50} {version:<12} {'-':>5}  did not start: {reason}")
                collected.append({"name": spec["name"], "package": spec["package"], "version": version, "error": reason, "tools": []})
                continue
            print(f"{spec['name']:<20} {spec['package']:<50} {version:<12} {len(listing['tools']):>5}  {listing['seconds']:>6.2f} s")
            collected.append({"name": spec["name"], "package": spec["package"], "version": version, **listing})
    os.makedirs(options.out, exist_ok=True)
    with open(os.path.join(options.out, "listings.json"), "w", encoding="utf-8") as handle:
        json.dump(collected, handle, indent=1, ensure_ascii=False)
    started = [server for server in collected if server["tools"]]
    print(f"\n{len(started)} of {len(collected)} servers listed their tools: {sum(len(s['tools']) for s in started)} tools in all")
    return 0 if started else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
