#!/usr/bin/env bash
# Everything the workflow runs. Usage: ./ci.sh <output directory>     (needs Python 3.13)
# No request leaves the machine: all four agents talk to a scripted stand-in on localhost.
set -uo pipefail
out="$(mkdir -p "$1" && cd "$1" && pwd)"
cd "$(dirname "$0")"
AS_OF="2026-11-15T00:00:00Z"   # unpinned dependencies are resolved as they stood on this day

python -m pip install --quiet uv || exit 2
venv="$(mktemp -d)/venv"
python -m uv venv --quiet "$venv" || exit 2
python -m uv pip install --quiet --python "$venv/bin/python" --exclude-newer "$AS_OF" -r requirements.txt || exit 2
"$venv/bin/python" -m lab.run "$out" 2> "$out/stderr.txt" | tee "$out/run.txt"
exit "${PIPESTATUS[0]}"
