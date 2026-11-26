#!/usr/bin/env bash
# Runs the comparison in AWS CloudShell (or anywhere with AWS credentials).
#   EMAIL=you@example.com ./run.sh            all steps except teardown
#   STEPS="verify" ./run.sh                   selected steps
#   ./run.sh teardown                         delete everything
# Output: results/*.json and results/run.log
set -euo pipefail
cd "$(dirname "$0")"
export AWS_REGION="${AWS_REGION:-eu-west-1}"
# boto3 1.44 needs Python 3.10+; CloudShell's system Python is older, so use uv's Python 3.13.
# CloudShell runs inside a virtualenv where `pip install --user` is refused, so uv goes into
# its own small virtualenv first.
if [ ! -x .venv/bin/python ]; then
  UV=$(command -v uv || true)
  if [ -z "$UV" ]; then
    python3 -m venv /tmp/uv-bootstrap
    /tmp/uv-bootstrap/bin/python -m pip install -q uv
    UV=/tmp/uv-bootstrap/bin/uv
  fi
  "$UV" venv -q -p 3.13 .venv
  "$UV" pip install -q --python .venv/bin/python -r requirements.txt
fi
PY=.venv/bin/python
$PY -m pytest -q tests
mkdir -p results
if [ "${1:-}" = teardown ]; then
  $PY -m bench.cli teardown 2>&1 | tee -a results/run.log
  exit 0
fi
STEPS="${STEPS:-setup data batchwrite standard rerun accelerated import errors verify}"
for step in $STEPS; do
  echo "=== $step" | tee -a results/run.log
  if [ "$step" = setup ]; then
    $PY -m bench.cli setup "${EMAIL:-}" 2>&1 | tee -a results/run.log
  else
    $PY -m bench.cli "$step" 2>&1 | tee -a results/run.log
  fi
done
echo "done: results in $(pwd)/results"
