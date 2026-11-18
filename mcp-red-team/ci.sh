#!/usr/bin/env bash
# Everything the workflow runs. Usage: ./ci.sh <output directory>     (needs Python 3.13)
# Every server here is a local process on stdio; the two HTTP stand-ins listen on 127.0.0.1 only.
# All "secrets" are fake strings created for the run and labelled FAKE.
set -uo pipefail
out="$(mkdir -p "$1" && cd "$1" && pwd)"
cd "$(dirname "$0")"
AS_OF="2026-02-16T00:00:00Z"   # unpinned dependencies are resolved as they stood on this day

python -m pip install --quiet uv || exit 2
env="$(mktemp -d)/env"
python -m uv venv --quiet "$env" && python -m uv pip install --quiet --python "$env/bin/python" --exclude-newer "$AS_OF" -r requirements.txt || exit 2
py="$env/bin/python"
failed=0

{
  echo "== 1. versions"
  "$py" --version
  "$py" -c "import importlib.metadata as m; print(*[f'{p} {m.version(p)}' for p in ('mcp', 'pydantic', 'jsonschema', 'anyio')], sep='\n')"
  "$py" -c "import mcp.types as t; print('protocol revision', t.LATEST_PROTOCOL_VERSION)"
  uname -srm; nproc | sed 's/$/ vCPU/'
} 2>&1 | tee "$out/01-versions.txt"

{
  echo "== 2. unit tests for the scanner and the pin store"
  "$py" tests/run.py 2>&1 | tail -n 4
} 2>&1 | tee "$out/02-unit-tests.txt"
grep -q "^OK" "$out/02-unit-tests.txt" || failed=1

{
  echo "== 3. the red-team run"
  "$py" lab/run.py "$out" 2> "$out/lab.stderr.txt"
} 2>&1 | tee "$out/03-red-team.txt"
[ "${PIPESTATUS[0]}" -eq 0 ] || failed=1

exit $failed
