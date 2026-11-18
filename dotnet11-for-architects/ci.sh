#!/usr/bin/env bash
# Everything the workflow runs for this sample. Usage: ./ci.sh <output directory>
set -uo pipefail
out="$(mkdir -p "$1" && cd "$1" && pwd)"
cd "$(dirname "$0")"
status=0
step() { echo "== $1"; shift; "$@" || { echo "step failed"; status=1; }; }

step "tour"            bash -c "dotnet run --project src/Tour -c Release -- '$out/tour.json' 2>&1 | tee '$out/tour.txt'"
step "async, default"  bash -c "dotnet run --project src/AsyncStack -c Release --artifacts-path '$out/art-off' -- state-machines '$out/async-off.json' 2>&1 | tee '$out/async-off.txt'"
step "async, runtime"  bash -c "dotnet run --project src/AsyncStack -c Release -p:RuntimeAsync=on --artifacts-path '$out/art-on' -- runtime-async '$out/async-on.json' 2>&1 | tee '$out/async-on.txt'"
step "upgrade, net10"  bash -c "dotnet run --project src/UpgradeCheck -c Release -f net10.0 -- '$out/upgrade-net10.json' > '$out/upgrade-net10.txt' 2>&1"
step "upgrade, net11"  bash -c "dotnet run --project src/UpgradeCheck -c Release -f net11.0 -- '$out/upgrade-net11.json' > '$out/upgrade-net11.txt' 2>&1"
step "compare"         bash -c "python python/compare_runtimes.py '$out/upgrade-net10.json' '$out/upgrade-net11.json' | tee '$out/compare.txt'"
step "cpu tests"       bash -c "cd python && python test_check_cpu_baseline.py | tee '$out/cpu-tests.txt'"
step "cpu, this host"  bash -c "python python/check_cpu_baseline.py | tee '$out/cpu-host.json'"
rm -rf "$out/art-off" "$out/art-on"
exit $status
