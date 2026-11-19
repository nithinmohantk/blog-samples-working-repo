"""Check pinned Python dependencies for Linux arm64 (aarch64) wheels on PyPI.

For each name==version line in a lock or requirements file, the PyPI JSON API
lists the files published for that release. A package is ready if it ships a
pure-Python wheel or a manylinux/musllinux aarch64 wheel. Packages with only
an sdist will compile during the image build, which needs a toolchain in the
build stage and is where arm64 builds usually fail.

Usage:
    python check_wheels.py requirements.txt
"""
from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.request
from typing import Callable

PIN = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)(\[[^\]]*\])?\s*==\s*([^\s;#\\]+)")


def parse_pins(text: str) -> list[tuple[str, str]]:
    pins = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "-")):
            continue
        m = PIN.match(line)
        if m:
            pins.append((m.group(1), m.group(3)))
    return pins


def classify(filenames: list[str]) -> str:
    """'pure', 'aarch64', 'sdist-only', 'x86-only' or 'none'."""
    wheels = [f for f in filenames if f.endswith(".whl")]
    if any(f.endswith("-none-any.whl") for f in wheels):
        return "pure"
    if any(re.search(r"(manylinux|musllinux)[^-]*aarch64", f) for f in wheels):
        return "aarch64"
    if any(f.endswith((".tar.gz", ".zip")) for f in filenames):
        return "sdist-only"
    return "x86-only" if wheels else "none"


def pypi_files(name: str, version: str) -> list[str]:
    url = f"https://pypi.org/pypi/{name}/{version}/json"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())
    return [u["filename"] for u in data.get("urls", [])]


def check(pins: list[tuple[str, str]],
          fetch: Callable[[str, str], list[str]] = pypi_files) -> list[dict]:
    rows = []
    for name, version in pins:
        try:
            status = classify(fetch(name, version))
        except urllib.error.HTTPError as exc:
            status = "not-on-pypi" if exc.code == 404 else f"http-{exc.code}"
        rows.append({"package": name, "version": version, "status": status})
    return rows


READY = {"pure", "aarch64"}


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__)
        return 2
    with open(argv[0], encoding="utf-8") as fh:
        rows = check(parse_pins(fh.read()))
    for r in rows:
        mark = "ok" if r["status"] in READY else "CHECK"
        print(f"{r['package']:<30} {r['version']:<15} {r['status']:<12} {mark}")
    return 0 if all(r["status"] in READY for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
