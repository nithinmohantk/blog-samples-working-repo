#!/usr/bin/env bash
# The main sample: tests, the JSON Lines hand-off to Python, and the build that must fail.
# Usage: ./verify.sh <output directory>
set -uo pipefail
out="$(mkdir -p "$1" && cd "$1" && pwd)"
cd "$(dirname "$0")"
status=0

dotnet run --project tests/SelfTest -c Release -- "$out/outcomes.jsonl" 2>&1 | tee "$out/selftest.txt" || status=1
(cd python && python test_consume_outcomes.py) | tee "$out/python-tests.txt" || status=1
python python/consume_outcomes.py "$out/outcomes.jsonl" | tee "$out/python-consume.txt" || status=1

# Adding a fourth case must break the build at every switch that has not been updated.
dotnet build whatif/AddCase -c Release -nologo -v q > "$out/whatif-build.txt" 2>&1
code=$?
grep -oE "OutcomeHandlers.cs\([0-9]+,[0-9]+\): error CS[0-9]+: [^[]*" "$out/whatif-build.txt" | sort -u > "$out/whatif-errors.txt"
count=$(wc -l < "$out/whatif-errors.txt")
echo "what-if build exit code $code, $count distinct error(s)" | tee "$out/whatif.txt"
cat "$out/whatif-errors.txt" | tee -a "$out/whatif.txt"
if [ "$code" -eq 0 ] || [ "$count" -ne 3 ]; then echo "expected the build to fail at three switches"; status=1; fi
exit $status
