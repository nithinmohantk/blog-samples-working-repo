#!/usr/bin/env bash
# Everything the workflow runs. Usage: ./ci.sh <output directory>     (needs Docker and Python 3.12 with pytest)
set -uo pipefail
out="$(mkdir -p "$1" && cd "$1" && pwd)"
cd "$(dirname "$0")"
status=0
HAPI_IMAGE="hapiproject/hapi:v6.10.1"   # 28 November 2023, the newest starter image on 19 January 2024

echo "== unit tests"
python -m pytest -q tests 2>&1 | tee "$out/unit-tests.txt"; [ "${PIPESTATUS[0]}" -eq 0 ] || status=1

echo "== HAPI FHIR with bulk export enabled"
python data/seed.py
docker run -d --name hapi -p 127.0.0.1:8080:8080 \
  -e hapi.fhir.bulk_export_enabled=true -e hapi.fhir.fhir_version=R4 "$HAPI_IMAGE" > /dev/null || exit 2
python -u tools/run_experiments.py http://127.0.0.1:8080/fhir "$out" 2>&1 | tee "$out/run.txt"; [ "${PIPESTATUS[0]}" -eq 0 ] || status=1
docker logs hapi 2>&1 | grep -iE "bulk|export|error" | tail -40 > "$out/hapi-log-excerpt.txt"
docker rm -f hapi > /dev/null
{ echo "image $HAPI_IMAGE"; python --version; python -m pytest --version; } > "$out/versions.txt" 2>&1
exit $status
