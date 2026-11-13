#!/usr/bin/env bash
# Everything the workflow runs. Usage: ./ci.sh <output directory>     (needs Python 3.12 or later)
set -uo pipefail
out="$(mkdir -p "$1" && cd "$1" && pwd)"
cd "$(dirname "$0")"
AS_OF="2026-02-01T00:00:00Z"   # packages are resolved as they stood on this day

python -m pip install --quiet uv || exit 2
python -m uv venv --quiet "$out/.venv" || exit 2
python -m uv pip install --quiet --python "$out/.venv/bin/python" --exclude-newer "$AS_OF" openai tiktoken || exit 2
"$out/.venv/bin/python" --version | tee "$out/versions.txt"
"$out/.venv/bin/python" tests/run.py "$out" 2>&1 | tee "$out/run.txt"; status=${PIPESTATUS[0]}
rm -rf "$out/.venv"
exit "$status"
