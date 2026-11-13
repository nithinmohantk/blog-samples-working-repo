#!/usr/bin/env bash
# Everything the workflow runs. Usage: ./ci.sh <output directory>
set -uo pipefail
out="$(mkdir -p "$1" && cd "$1" && pwd)"
cd "$(dirname "$0")"
status=0
python --version | tee "$out/versions.txt"

echo "== target and role policy"
( cd gateway && python check_target.py target.json service-role-policy.json | tee "$out/lint.txt"; exit "${PIPESTATUS[0]}" ) || status=1
( cd gateway && python test_check_target.py | tee "$out/lint-tests.txt"; exit "${PIPESTATUS[0]}" ) || status=1
python -c "import json,sys; d=json.load(open('workflow/goodwill-credit.asl.json')); print('states:', len(d['States']), ' tasks:', sum(1 for s in d['States'].values() if s['Type']=='Task'), ' choices:', sum(1 for s in d['States'].values() if s['Type']=='Choice'))" | tee "$out/definition.txt"

echo "== workflow on Step Functions Local"
python -m pip install --quiet boto3 && python -c "import boto3; print('boto3', boto3.__version__)" | tee -a "$out/versions.txt"
docker run -d --name sfn-local -p 127.0.0.1:8083:8083 \
  -v "$PWD/workflow/mock-config.json:/home/StepFunctionsLocal/MockConfigFile.json:ro" \
  -e SFN_MOCK_CONFIG=/home/StepFunctionsLocal/MockConfigFile.json \
  amazon/aws-stepfunctions-local > /dev/null || status=1
docker image inspect amazon/aws-stepfunctions-local --format 'image {{index .RepoDigests 0}} created {{.Created}}' | tee -a "$out/versions.txt"
for i in $(seq 1 60); do (echo > /dev/tcp/127.0.0.1/8083) 2>/dev/null && break; sleep 1; done
python agent/run_scenarios.py http://127.0.0.1:8083 "$out/scenarios.json" 2>&1 | tee "$out/scenarios.txt"; [ "${PIPESTATUS[0]}" -eq 0 ] || status=1
docker logs sfn-local > "$out/sfn-local.log" 2>&1; head -n 5 "$out/sfn-local.log" | tee -a "$out/versions.txt"
docker rm -f sfn-local > /dev/null 2>&1
exit $status
