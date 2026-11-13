#!/usr/bin/env bash
# Everything the workflow runs. Usage: ./ci.sh <output directory>     (needs Docker and Python 3)
set -uo pipefail
out="$(mkdir -p "$1" && cd "$1" && pwd)"
cd "$(dirname "$0")"
status=0
SDK="10.0.201"                                  # 12 March 2026, carries runtime 10.0.5
HAPI_IMAGE="${HAPI_IMAGE:-hapiproject/hapi:v8.0.0}"
FHIR="http://127.0.0.1:8083/fhir"

# A private SDK, so the build cannot roll forward to whatever newer .NET the machine carries.
root="$(mktemp -d)"
curl -fsSL -o "$root/dotnet-install.sh" https://dot.net/v1/dotnet-install.sh || exit 2
bash "$root/dotnet-install.sh" --version "$SDK" --install-dir "$root/sdk" --no-path > "$out/install.txt" 2>&1 || exit 2
export DOTNET_ROOT="$root/sdk" DOTNET_MULTILEVEL_LOOKUP=0 DOTNET_NOLOGO=1 DOTNET_CLI_TELEMETRY_OPTOUT=1
dotnet="$root/sdk/dotnet"
python -m pip install --quiet "PyJWT==2.12.1" "cryptography==46.0.6" 2>&1 | tail -n 1

{
  echo ".NET SDK $("$dotnet" --version), runtime $("$dotnet" --list-runtimes | awk '/Microsoft.AspNetCore.App/ {print $2}')"
  python --version
  python -c "import jwt, cryptography; print('PyJWT', jwt.__version__, 'cryptography', cryptography.__version__)"
  echo "$HAPI_IMAGE"
} | tee "$out/versions.txt"

echo "== against an in-memory stand-in for the FHIR server"
"$dotnet" run --project tests/SelfTest -c Release -- "$out/stand-in" 2>&1 | tee "$out/selftest-stand-in.txt"; [ "${PIPESTATUS[0]}" -eq 0 ] || status=1

echo "== against HAPI FHIR, with a Python client as well"
# The FHIR server listens on loopback only. In a deployment it sits on a network the callers cannot reach at all.
docker run -d --name hapi-smart -p 127.0.0.1:8083:8080 "$HAPI_IMAGE" > /dev/null || status=1
for i in $(seq 1 120); do curl -fsS "$FHIR/metadata" > /dev/null 2>&1 && break; sleep 3; done
"$dotnet" run --project tests/SelfTest -c Release --no-build -- "$out/hapi" "$FHIR" python/verify_interop.py 2>&1 | tee "$out/selftest-hapi.txt"; [ "${PIPESTATUS[0]}" -eq 0 ] || status=1

docker logs hapi-smart 2>&1 | grep -i "error\|exception" | tail -n 40 > "$out/hapi-errors.log"; docker rm -f hapi-smart > /dev/null 2>&1
# Nothing that could be a key or a token may be among the published results.
if grep -rlE "BEGIN [A-Z ]*PRIVATE KEY|eyJ[A-Za-z0-9_-]{20,}\.eyJ" "$out" > "$out/leak-check.txt" 2>/dev/null; then echo "a key or token was written to the output"; status=1; else echo "no key or token in the output" | tee "$out/leak-check.txt"; fi
exit $status
