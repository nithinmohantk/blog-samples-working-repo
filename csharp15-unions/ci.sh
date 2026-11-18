#!/usr/bin/env bash
set -uo pipefail
out="$(mkdir -p "$1/unions" && cd "$1/unions" && pwd)"
cd "$(dirname "$0")"
status=0
./run_experiments.sh "$out/experiments" > /dev/null || status=1
if [ -x ./verify.sh ]; then ./verify.sh "$out" || status=1; fi
exit $status
