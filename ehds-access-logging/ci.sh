#!/usr/bin/env bash
# Everything the workflow runs. Usage: ./ci.sh <output directory>     (needs Docker and Python 3.12 with pytest)
set -uo pipefail
out="$(mkdir -p "$1" && cd "$1" && pwd)"
cd "$(dirname "$0")"
status=0
HAPI_IMAGE="hapiproject/hapi:v7.0.3"   # tagged 7 March 2024, the newest starter image on 22 March 2024

echo "== unit tests"
python -m pytest -q 2>&1 | tee "$out/unit-tests.txt"; [ "${PIPESTATUS[0]}" -eq 0 ] || status=1

echo "== HAPI FHIR"
python data/seed.py
docker run -d --name hapi -p 127.0.0.1:8080:8080 -e hapi.fhir.fhir_version=R4 "$HAPI_IMAGE" > /dev/null || exit 2
python -u tools/run_experiments.py http://127.0.0.1:8080/fhir "$out" 2>&1 | tee "$out/run-log.txt"; [ "${PIPESTATUS[0]}" -eq 0 ] || status=1
docker logs hapi 2>&1 | grep -iE "HAPI-[0-9]+|error" | tail -30 > "$out/hapi-log-excerpt.txt"
docker rm -f hapi > /dev/null
{ echo "image $HAPI_IMAGE"; docker image inspect "$HAPI_IMAGE" --format '{{index .RepoDigests 0}}' 2>/dev/null; python --version; python -m pytest --version; } > "$out/versions.txt" 2>&1
exit $status
