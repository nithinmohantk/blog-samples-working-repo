#!/usr/bin/env bash
# Everything the workflow runs. Usage: ./ci.sh <output directory>     (needs Docker, Java 17 or later, Python 3)
set -uo pipefail
out="$(mkdir -p "$1" && cd "$1" && pwd)"
cd "$(dirname "$0")"
status=0
SDK="10.0.201"                                  # 12 March 2026, carries runtime 10.0.5
VALIDATOR="6.8.2"                               # 1 March 2026
VALIDATOR_SHA256="b7e3de5494c6ea18e753942c1dea1aa37e6fa2b47ea30cfc046dc5b707104868"
HAPI_IMAGE="${HAPI_IMAGE:-hapiproject/hapi:v8.0.0}"
FHIR="http://127.0.0.1:8082/fhir"

# A private SDK, so the build cannot roll forward to whatever newer .NET the machine carries.
root="$(mktemp -d)"
curl -fsSL -o "$root/dotnet-install.sh" https://dot.net/v1/dotnet-install.sh || exit 2
bash "$root/dotnet-install.sh" --version "$SDK" --install-dir "$root/sdk" --no-path > "$out/install.txt" 2>&1 || exit 2
export DOTNET_ROOT="$root/sdk" DOTNET_MULTILEVEL_LOOKUP=0 DOTNET_NOLOGO=1 DOTNET_CLI_TELEMETRY_OPTOUT=1
dotnet="$root/sdk/dotnet"

curl -fsSL -o "$root/validator_cli.jar" "https://github.com/hapifhir/org.hl7.fhir.core/releases/download/$VALIDATOR/validator_cli.jar" || exit 2
actual="$(sha256sum "$root/validator_cli.jar" | cut -d' ' -f1)"
if [ "$actual" != "$VALIDATOR_SHA256" ]; then echo "validator checksum mismatch: $actual"; exit 2; fi

{
  echo ".NET SDK $("$dotnet" --version), runtime $("$dotnet" --list-runtimes | awk '/Microsoft.NETCore.App/ {print $2}')"
  python --version
  java -version 2>&1 | head -n 1
  echo "HL7 validator $VALIDATOR sha256 $actual"
  echo "$HAPI_IMAGE"
} | tee "$out/versions.txt"

docker run -d --name hapi-adt -p 127.0.0.1:8082:8080 "$HAPI_IMAGE" > /dev/null || status=1

echo "== reader, times, mapping and acknowledgements, then the same messages through a FHIR server"
for i in $(seq 1 120); do curl -fsS "$FHIR/metadata" > /dev/null 2>&1 && break; sleep 3; done
"$dotnet" run --project tests/SelfTest -c Release -- messages "$out" "$FHIR" 2>&1 | tee "$out/selftest.txt"; [ "${PIPESTATUS[0]}" -eq 0 ] || status=1

echo "== an independent check of the server state"
python python/verify_server_state.py "$out" 2>&1 | tee "$out/verify.txt"; [ "${PIPESTATUS[0]}" -eq 0 ] || status=1

echo "== the HL7 validator on what was sent"
python python/validate_output.py "$root/validator_cli.jar" "$out" --tx https://tx.fhir.org https://tx.ontoserver.csiro.au/fhir 2>&1 | tee "$out/validation.txt"; [ "${PIPESTATUS[0]}" -eq 0 ] || status=1

docker logs hapi-adt 2>&1 | grep -i "error\|exception" | tail -n 40 > "$out/hapi-errors.log"; docker rm -f hapi-adt > /dev/null 2>&1
exit $status
