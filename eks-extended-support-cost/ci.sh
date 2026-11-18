#!/usr/bin/env bash
# Everything the workflow runs. Usage: ./ci.sh <output directory>
set -uo pipefail
out="$(mkdir -p "$1" && cd "$1" && pwd)"
cd "$(dirname "$0")"
status=0
export PYTHONWARNINGS=ignore
python --version > "$out/versions.txt" 2>&1
python -c 'import importlib.metadata as m; [print(p, m.version(p)) for p in ("boto3", "botocore", "moto", "pytest")]' >> "$out/versions.txt"

echo "== unit tests"
python -m pytest -q -p no:warnings 2>&1 | tee "$out/unit-tests.txt"; [ "${PIPESTATUS[0]}" -eq 0 ] || status=1
echo "== demo fleet"
python tools/demo_fleet.py "$out/demo-fleet.json" 2>&1 | grep -v '^INFO' | tee "$out/demo-fleet.txt"; [ "${PIPESTATUS[0]}" -eq 0 ] || status=1
echo "== what the EKS model offered"
python tools/api_check.py 2>&1 | tee "$out/api-check.txt"; [ "${PIPESTATUS[0]}" -eq 0 ] || status=1
exit $status
