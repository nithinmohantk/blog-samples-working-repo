#!/usr/bin/env bash
# Everything the workflow runs for this sample. Usage: ./ci.sh <output directory>   (needs the .NET 11 SDK)
# Without MODEL_ENDPOINT, MODEL_API_KEY and MODEL_NAME only the offline part runs, on the scripted stand-in.
# With them, the lab talks to that model: about 80 short conversations per model at the default LAB_RUNS=5.
set -uo pipefail
out="$(mkdir -p "$1" && cd "$1" && pwd)"
cd "$(dirname "$0")"
status=0

{
  echo "== 1. versions"
  dotnet --version
  uname -srm
  dotnet restore tests/Desk.Tests -v q 2>&1 | grep -E "error|warn" | sort -u | head -n 10
  dotnet list tests/Desk.Tests package --include-transitive 2>/dev/null | grep -E "> (OpenAI|Microsoft.Extensions.AI|Microsoft.Extensions.AI.OpenAI|Microsoft.Extensions.AI.Abstractions|AGUI\.[A-Za-z]+|System.ClientModel) " | sed 's/  */ /g' | sort -u
} 2>&1 | tee "$out/01-versions.txt"

{
  echo "== 2. build"
  dotnet build tests/Desk.Tests -c Release -v q 2>&1 | grep -E "error|warn|Build succeeded|Warning\(s\)|Error\(s\)" | sort -u | head -n 60
} 2>&1 | tee "$out/02-build.txt"
grep -q "Build succeeded" "$out/02-build.txt" || status=1

{
  echo "== 3. offline tests: the pipeline on the scripted stand-in"
  MODEL_API_KEY= dotnet test tests/Desk.Tests -c Release --no-build --filter "FullyQualifiedName~OfflineTests" --logger "console;verbosity=normal" 2>&1 | grep -E "^\s+(Passed|Failed|Skipped) |Error Message|Assert\.|Expected|Actual|Total tests|Passed:|Failed:|Test Run|Passed!|Failed!" | head -n 60
} 2>&1 | tee "$out/03-offline.txt"
grep -qE "Test Run Successful|Passed!" "$out/03-offline.txt" || status=1

{
  echo "== 4. the lab: a real model behind the same agent service"
  rm -f "$out/model-lab.txt" "$out/model-runs.jsonl"
  DESK_OUT="$out" dotnet test tests/Desk.Tests -c Release --no-build --filter "FullyQualifiedName~RealModelLab" 2>&1 | grep -E "Passed!|Failed!|Error Message|Exception" | head -n 20
  cat "$out/model-lab.txt" 2>/dev/null
} 2>&1 | tee "$out/04-lab.txt"

exit $status
