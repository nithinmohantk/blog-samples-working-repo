#!/usr/bin/env bash
# Everything the workflow runs. Usage: ./ci.sh <output directory>
set -uo pipefail
out="$(mkdir -p "$1" && cd "$1" && pwd)"
cd "$(dirname "$0")"
status=0
export TF_IN_AUTOMATION=1 TF_CLI_ARGS="-no-color" CHECKPOINT_DISABLE=1 DOTNET_NOLOGO=1
{ dotnet --version; python --version; terraform version | head -1; tofu version | head -1; } | tee "$out/versions.txt"

echo "== simulation: Python and C#"
python python/simulate.py "$out/simulation-python.json" | tee "$out/simulation.txt"
dotnet run --project tests/SelfTest -c Release -- "$out/simulation-dotnet.json" 2>&1 | tee "$out/selftest.txt"; [ "${PIPESTATUS[0]}" -eq 0 ] || status=1
python -c "import json,sys; a=json.load(open(sys.argv[1])); b=json.load(open(sys.argv[2])); print('Python and C# simulations agree:', a==b); sys.exit(0 if a==b else 1)" \
  "$out/simulation-python.json" "$out/simulation-dotnet.json" | tee "$out/agree.txt"; [ "${PIPESTATUS[0]}" -eq 0 ] || status=1

echo "== drill: two instances of the API"
dotnet build src/ActiveActive.Api -c Release -o "$out/api-bin" > "$out/api-build.txt" 2>&1 || { status=1; tail -n 20 "$out/api-build.txt"; }
REGION_NAME=north ASPNETCORE_URLS=http://127.0.0.1:5081 dotnet "$out/api-bin/ActiveActive.Api.dll" > "$out/api-north.log" 2>&1 & north=$!
REGION_NAME=west  ASPNETCORE_URLS=http://127.0.0.1:5082 dotnet "$out/api-bin/ActiveActive.Api.dll" > "$out/api-west.log" 2>&1 & west=$!
for i in $(seq 1 60); do curl -fsS http://127.0.0.1:5081/healthz > /dev/null 2>&1 && curl -fsS http://127.0.0.1:5082/healthz > /dev/null 2>&1 && break; sleep 0.5; done
python python/drill.py http://127.0.0.1:5081 http://127.0.0.1:5082 | tee "$out/drill.txt"; [ "${PIPESTATUS[0]}" -eq 0 ] || status=1
kill $north $west 2>/dev/null; wait 2>/dev/null
grep -c "Patient/" "$out/api-north.log" "$out/api-west.log" | tee "$out/log-check.txt"
rm -rf "$out/api-bin"

echo "== infrastructure"
( cd infra && terraform init -input=false > "$out/infra-init.txt" 2>&1 && terraform validate > "$out/infra-validate.txt" 2>&1 \
  && terraform test 2>&1 | tee "$out/infra-terraform-test.txt"; exit "${PIPESTATUS[0]}" ) || { status=1; tail -n 60 "$out/infra-validate.txt" 2>/dev/null; }
work="$(mktemp -d)"; cp -r infra/. "$work/" && rm -rf "$work/.terraform"
sed -i 's|registry.terraform.io|registry.opentofu.org|; /^  hashes = \[/,/^  \]/d' "$work/.terraform.lock.hcl"
( cd "$work" && tofu init -input=false > "$out/infra-tofu-init.txt" 2>&1 && tofu test 2>&1 | tee "$out/infra-tofu-test.txt"; exit "${PIPESTATUS[0]}" ) || { echo "tofu: FAILED" | tee -a "$out/infra-tofu-test.txt"; status=1; }
exit $status
