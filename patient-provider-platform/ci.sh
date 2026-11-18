#!/usr/bin/env bash
# Everything the workflow runs. Usage: ./ci.sh <output directory>
set -uo pipefail
out="$(mkdir -p "$1" && cd "$1" && pwd)"
cd "$(dirname "$0")"
status=0
export DOTNET_NOLOGO=1
HAPI_IMAGE="${HAPI_IMAGE:-hapiproject/hapi:v8.0.0}"
{ dotnet --version; python --version; echo "$HAPI_IMAGE"; } | tee "$out/versions.txt"

echo "== FHIR server"
docker run -d --name hapi -p 127.0.0.1:8080:8080 "$HAPI_IMAGE" > /dev/null || status=1
docker image inspect "$HAPI_IMAGE" --format 'image {{index .RepoDigests 0}} created {{.Created}}' | tee -a "$out/versions.txt"

echo "== booking core (in memory)"
dotnet run --project tests/SelfTest -c Release 2>&1 | tee "$out/selftest.txt"; [ "${PIPESTATUS[0]}" -eq 0 ] || status=1

echo "== FHIR interactions against the server"
for i in $(seq 1 120); do curl -fsS http://127.0.0.1:8080/fhir/metadata > /dev/null 2>&1 && break; sleep 3; done
python python/fhir_drill.py http://127.0.0.1:8080/fhir "$out/fhir-drill.json" 2>&1 | tee "$out/fhir-drill.txt"; [ "${PIPESTATUS[0]}" -eq 0 ] || status=1
dotnet run --project tests/SelfTest -c Release --no-build -- http://127.0.0.1:8080/fhir 2>&1 | tee "$out/selftest-fhir.txt"; [ "${PIPESTATUS[0]}" -eq 0 ] || status=1
docker logs hapi 2>&1 | tail -n 40 > "$out/hapi-tail.log"; docker rm -f hapi > /dev/null 2>&1
exit $status
