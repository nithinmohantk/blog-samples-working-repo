#!/usr/bin/env bash
# Everything the workflow runs. Usage: ./ci.sh <output directory>
set -uo pipefail
out="$(mkdir -p "$1" && cd "$1" && pwd)"
cd "$(dirname "$0")"
status=0
export DOTNET_NOLOGO=1
HAPI_IMAGE="${HAPI_IMAGE:-hapiproject/hapi:v8.0.0}"
{ dotnet --version; python --version; echo "$HAPI_IMAGE"; } | tee "$out/versions.txt"
docker run -d --name hapi-rx -p 127.0.0.1:8081:8080 "$HAPI_IMAGE" > /dev/null || status=1

echo "== the rules"
dotnet run --project tests/SelfTest -c Release 2>&1 | tee "$out/rules.txt"; [ "${PIPESTATUS[0]}" -eq 0 ] || status=1

echo "== the same rules through a FHIR server"
for i in $(seq 1 120); do curl -fsS http://127.0.0.1:8081/fhir/metadata > /dev/null 2>&1 && break; sleep 3; done
dotnet run --project tests/SelfTest -c Release --no-build -- http://127.0.0.1:8081/fhir "$out/ids.json" 2>&1 | tee "$out/server.txt"; [ "${PIPESTATUS[0]}" -eq 0 ] || status=1

echo "== an independent check of the server state"
python python/verify_server_state.py http://127.0.0.1:8081/fhir "$out/ids.json" "$out/server-state.json" 2>&1 | tee "$out/verify.txt"; [ "${PIPESTATUS[0]}" -eq 0 ] || status=1
docker logs hapi-rx 2>&1 | grep -i "error\|exception" | tail -n 30 > "$out/hapi-errors.log"; docker rm -f hapi-rx > /dev/null 2>&1
exit $status
