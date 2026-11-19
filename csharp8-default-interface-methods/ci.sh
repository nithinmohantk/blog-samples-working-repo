#!/usr/bin/env bash
# Builds and runs everything as C# 8.0. Usage: ./ci.sh <output directory>
set -uo pipefail
out="$(mkdir -p "$1" && cd "$1" && pwd)"
cd "$(dirname "$0")"
failed=0

{
  echo "== 1. two programs, compiled as C# 8.0"
  for project in Vehicles Evolve experiments/03-most-specific-wins; do
    echo "-- $project"
    dotnet run --project "$project" -c Release 2>&1 | grep -v "^$" || failed=1
  done
} 2>&1 | tee "$out/01-programs.txt"

expect() {  # expect <project> <error code>: the build must fail with exactly this error
  echo "-- $1 (expected: $2)"
  dotnet build "$1" -c Release 2>&1 | grep -oE "error CS[0-9]+: [^[]*" | sed 's/ *$//' | sort -u | tee "$out/.last"
  [ "$(grep -c "error $2:" "$out/.last")" = "1" ] && [ "$(wc -l < "$out/.last")" = "1" ] || { echo "UNEXPECTED"; failed=1; }
}
{
  echo "== 2. three programs that must not compile"
  expect experiments/01-call-through-class CS1061
  expect experiments/02-two-defaults-clash CS8705
  expect experiments/04-csharp-7-3 CS8370
} 2>&1 | tee "$out/02-experiments.txt"
rm -f "$out/.last"
grep -q UNEXPECTED "$out/02-experiments.txt" && failed=1

{ echo "== 3. built with"; dotnet --version; } 2>&1 | tee "$out/03-sdk.txt"
exit $failed
