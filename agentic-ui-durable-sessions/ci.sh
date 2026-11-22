#!/usr/bin/env bash
set -uo pipefail
out="$(mkdir -p "$1" && cd "$1" && pwd)"
cd "$(dirname "$0")"
rm -f "$out/thread-lab.txt"
dotnet build tests/Desk.Tests -c Release -v q 2>&1 | grep -E "error|warn|Build succeeded" | sort -u | head -n 40 | tee "$out/02-build.txt"
DESK_OUT="$out" dotnet test tests/Desk.Tests -c Release --no-build 2>&1 | tail -n 15 | tee "$out/03-tests.txt"
exit 0
