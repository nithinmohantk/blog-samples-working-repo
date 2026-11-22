#!/usr/bin/env bash
set -uo pipefail
out="$(mkdir -p "$1" && cd "$1" && pwd)"
cd "$(dirname "$0")"
dotnet run --project tools/Probe -c Release > "$out/00-probe.txt" 2> "$out/00-probe-err.txt"
tail -n 20 "$out/00-probe-err.txt"
wc -l "$out/00-probe.txt"
