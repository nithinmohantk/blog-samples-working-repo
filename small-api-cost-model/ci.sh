#!/usr/bin/env bash
# Everything the workflow runs. Usage: ./ci.sh <output directory>     (needs Python 3.11 or later, nothing else)
set -uo pipefail
out="$(mkdir -p "$1" && cd "$1" && pwd)"
cd "$(dirname "$0")"
status=0
python --version | tee "$out/versions.txt"
echo "== the model against worked examples from the pricing pages, and its own arithmetic"
python -m unittest -v test_model 2>&1 | tee "$out/tests.txt"; [ "${PIPESTATUS[0]}" -eq 0 ] || status=1
echo "== the tables"
python model.py --json "$out/model.json" 2>&1 | tee "$out/model.txt"; [ "${PIPESTATUS[0]}" -eq 0 ] || status=1
cp prices.json "$out/prices.json"
exit $status
