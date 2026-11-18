#!/usr/bin/env bash
# Everything the workflow runs for this sample. Usage: ./ci.sh <output directory>   (needs the .NET 11 SDK and Python 3)
# Nothing here calls a model or a cloud service. The model is the scripted stand-in in src/Desk.Core.
set -uo pipefail
out="$(mkdir -p "$1" && cd "$1" && pwd)"
cd "$(dirname "$0")"
status=0

{
  echo "== 1. versions"
  dotnet --version
  dotnet --list-runtimes | grep -E "AspNetCore.App 11|NETCore.App 11"
  uname -srm
} 2>&1 | tee "$out/01-versions.txt"

{
  echo "== 2. build"
  dotnet build tests/Desk.Tests -c Release -v q 2>&1 | grep -E "error|warn|Build succeeded|Warning\(s\)|Error\(s\)" | sort -u | head -n 60
  dotnet list tests/Desk.Tests package --include-transitive 2>/dev/null | grep -E "Components.AI |AGUI\.|Extensions.AI |Extensions.AI.Abstractions|bunit |Mvc.Testing|xunit " | sed 's/  */ /g' | sort -u
} 2>&1 | tee "$out/02-build.txt"
grep -q "Build succeeded" "$out/02-build.txt" || status=1

{
  echo "== 3. tests: the agent alone, the agent over AG-UI, the component in bUnit"
  rm -f "$out/wire-traces.txt"
  DESK_OUT="$out" dotnet test tests/Desk.Tests -c Release --no-build --logger "console;verbosity=normal" 2>&1 | grep -E "^\s+(Passed|Failed|Skipped) |Error Message|Assert\.|Expected|Actual|Exception|   at Desk|Total tests|Passed:|Failed:|Test Run|Passed!|Failed!" | head -n 150
} 2>&1 | tee "$out/03-tests.txt"
grep -qE "Test Run Successful|Passed!" "$out/03-tests.txt" || status=1

exit $status
