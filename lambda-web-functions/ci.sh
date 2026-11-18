#!/usr/bin/env bash
# Everything the workflow runs. Usage: ./ci.sh <output directory>
set -uo pipefail
out="$(mkdir -p "$1" && cd "$1" && pwd)"
cd "$(dirname "$0")"
status=0
node --version | tee "$out/versions.txt"; python --version | tee -a "$out/versions.txt"
( cd app && node --test test/*.test.js 2>&1 | tee "$out/node-tests.txt"; exit "${PIPESTATUS[0]}" ) || status=1
( cd app && node measure.js "$out/metrics.json" ) || status=1
# The server as a process, the way the platform starts it: listen where told, answer, leave on SIGTERM.
( cd app; AWS_LAMBDA_HTTP_ENDPOINT=127.0.0.1:38080 node index.js > "$out/process.txt" 2>&1 & pid=$!
  for i in $(seq 1 50); do curl -fsS http://127.0.0.1:38080/healthz > "$out/process-health.txt" 2>/dev/null && break; sleep 0.1; done
  started=$(date +%s.%N); kill -TERM $pid; wait $pid; code=$?
  printf 'exit code %s, %.3f s after SIGTERM\n' "$code" "$(echo "$(date +%s.%N) - $started" | bc)" >> "$out/process.txt"
  grep -q '"status":"ok"' "$out/process-health.txt" && [ "$code" -eq 0 ] ) || status=1
cat "$out/process.txt"
( cd cost && python test_model.py | tee "$out/cost-tests.txt"; exit "${PIPESTATUS[0]}" ) || status=1
python cost/model.py | tee "$out/cost-table.txt"
python cost/model.py --json > "$out/cost-table.json"
exit $status
