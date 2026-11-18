#!/usr/bin/env bash
# Everything the workflow runs. Usage: ./ci.sh <output directory>   (needs Python 3.12 with the pinned packages)
set -uo pipefail
out="$(mkdir -p "$1" && cd "$1" && pwd)"
cd "$(dirname "$0")"
status=0
export PYTHONWARNINGS=ignore

echo "== unit tests"
python -m pytest -q -p no:warnings 2>&1 | tee "$out/unit-tests.txt"; [ "${PIPESTATUS[0]}" -eq 0 ] || status=1

echo "== audit of the made-up demo account (moto)"
python tools/demo_account.py "$out" 2>&1 | tee "$out/demo-summary.txt"; [ "${PIPESTATUS[0]}" -eq 0 ] || status=1

echo "== clean-up steps, priced"
python tools/scenarios.py 2>&1 | tee "$out/scenarios.txt"; [ "${PIPESTATUS[0]}" -eq 0 ] || status=1

echo "== API options in the January 2024 botocore model"
python tools/api_options.py 2>&1 | tee "$out/api-options.txt"; [ "${PIPESTATUS[0]}" -eq 0 ] || status=1

python --version > "$out/versions.txt" 2>&1
python -c 'import importlib.metadata as m; [print(p, m.version(p)) for p in ("boto3", "botocore", "moto", "pytest")]' >> "$out/versions.txt"
exit $status
