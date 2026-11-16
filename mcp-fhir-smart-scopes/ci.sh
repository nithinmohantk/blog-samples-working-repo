#!/usr/bin/env bash
# Everything the workflow runs. Usage: ./ci.sh <output directory>     (needs Python 3.13 and Docker)
# All servers listen on 127.0.0.1 only. All data is synthetic. Signing keys are generated per run
# in a temporary directory and are never written to the output.
set -uo pipefail
out="$(mkdir -p "$1" && cd "$1" && pwd)"
cd "$(dirname "$0")"
AS_OF="2026-04-07T00:00:00Z"   # unpinned dependencies are resolved as they stood on this day
HAPI_IMAGE="${HAPI_IMAGE:-hapiproject/hapi:v8.0.0}"
FHIR="http://127.0.0.1:8084/fhir"

python -m pip install --quiet uv || exit 2
env="$(mktemp -d)/env"
python -m uv venv --quiet "$env" && python -m uv pip install --quiet --python "$env/bin/python" --exclude-newer "$AS_OF" -r requirements.txt || exit 2
py="$env/bin/python"
failed=0

{
  echo "== 1. versions"
  "$py" --version
  "$py" -c "import importlib.metadata as m; print(*[f'{p} {m.version(p)}' for p in ('mcp', 'PyJWT', 'cryptography', 'httpx', 'uvicorn', 'starlette', 'pydantic')], sep='\n')"
  "$py" -c "import mcp.types as t; print('protocol revision', t.LATEST_PROTOCOL_VERSION)"
  echo "$HAPI_IMAGE"
  uname -srm
} 2>&1 | tee "$out/01-versions.txt"

{
  echo "== 2. unit tests for the scope parser, the policy and the judge"
  "$py" tests/run.py 2>&1 | tail -n 4
} 2>&1 | tee "$out/02-unit-tests.txt"
grep -q "^OK" "$out/02-unit-tests.txt" || failed=1

{
  echo "== 3. the lab against the in-memory stand-in"
  "$py" -m lab.run "$out/standin"
} 2>&1 | tee "$out/03-lab-standin.txt"
[ "${PIPESTATUS[0]}" -eq 0 ] || failed=1

{
  echo "== 4. the lab against HAPI FHIR"
  docker run -d --name hapi-mcp -p 127.0.0.1:8084:8080 "$HAPI_IMAGE" > /dev/null
  for i in $(seq 1 120); do curl -fsS "$FHIR/metadata" > /dev/null 2>&1 && break; sleep 3; done
  "$py" -m lab.run "$out/hapi" "$FHIR"
} 2>&1 | tee "$out/04-lab-hapi.txt"
[ "${PIPESTATUS[0]}" -eq 0 ] || failed=1
docker logs hapi-mcp 2>&1 | grep -i "error\|exception" | tail -n 40 > "$out/hapi-errors.log"; docker rm -f hapi-mcp > /dev/null 2>&1

# Nothing that could be a key or a token may be among the published results.
if grep -rlE "BEGIN [A-Z ]*PRIVATE KEY|eyJ[A-Za-z0-9_-]{20,}\.eyJ" "$out" > "$out/leak-check.txt" 2>/dev/null; then echo "a key or token was written to the output"; failed=1; else echo "no key or token in the output" | tee "$out/leak-check.txt"; fi
exit $failed
