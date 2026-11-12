#!/usr/bin/env bash
# Builds and runs each experiment on its own, and records the compiler diagnostics and the output.
# An experiment that fails to compile is a result, not an error. Usage: ./run_experiments.sh <output directory>
set -uo pipefail
out="$(mkdir -p "$1" && cd "$1" && pwd)"
cd "$(dirname "$0")/experiments"
for dir in e*/; do
  name="${dir%/}"
  project="$name"; [ -d "$name/App" ] && project="$name/App"
  {
    echo "### $name"
    build="$(dotnet build "$project" -c Release -nologo -v q 2>&1)"
    if [ $? -eq 0 ]; then echo "build: succeeded"; else echo "build: FAILED"; fi
    echo "$build" | grep -oE "(error|warning) [A-Z]+[0-9]+: [^[]*" | sort -u | sed 's/^/  /'
    if echo "$build" | grep -q "Build succeeded"; then
      echo "output:"
      dotnet run --project "$project" -c Release --no-build 2>&1 | sed 's/^/  /'
    fi
    echo
  } | tee "$out/$name.txt"
done
cat "$out"/e*.txt > "$out/experiments.txt"
