#!/usr/bin/env bash
# Everything the workflow runs. Usage: ./ci.sh <output directory>     (needs Python 3.13 and Docker)
# The model is a scripted stand-in. No hosted model and no cloud service is called.
set -uo pipefail
out="$(mkdir -p "$1" && cd "$1" && pwd)"
cd "$(dirname "$0")"
AS_OF="2026-09-14T00:00:00Z"   # unpinned dependencies are resolved as they stood on this day
work="$(mktemp -d)"
failed=0

python -m pip install --quiet uv || exit 2
python -m uv venv --quiet "$work/venv" && python -m uv pip install --quiet --python "$work/venv/bin/python" --exclude-newer "$AS_OF" -r requirements.txt || exit 2
py="$work/venv/bin/python"

{
  echo "== 1. versions"
  "$py" --version
  "$py" -c "import importlib.metadata as m; print(*[f'{p} {m.version(p)}' for p in ('jsonschema', 'opentelemetry-api', 'opentelemetry-sdk')], sep='\n')"
  "$py" -c "import sqlite3; print('sqlite', sqlite3.sqlite_version)"
  docker --version
  docker pull --quiet python:3.13-slim > /dev/null && docker run --rm python:3.13-slim python --version | sed 's/^/sandbox image python:3.13-slim: /'
  uname -srm
} 2>&1 | tee "$out/01-versions.txt"

{
  echo "== 2. the harness's own tests"
  "$py" -m unittest discover -s tests -t . 2>&1 | tail -n 4
} 2>&1 | tee "$out/02-tests.txt"
grep -q "^OK" "$out/02-tests.txt" || failed=1

{
  echo "== 3. eleven bad days: bare loop, harness, and the container sandbox for generated code"
  "$py" -m lab.run "$out" --docker
} 2>&1 | tee "$out/03-lab.txt"
[ "${PIPESTATUS[0]}" -eq 0 ] || failed=1

{
  echo "== 4. size of each part"
  wc -l harness/bare.py harness/loop.py harness/tools.py harness/budget.py harness/policy.py harness/store.py harness/sandbox.py
} 2>&1 | tee "$out/04-size.txt"

exit $failed
