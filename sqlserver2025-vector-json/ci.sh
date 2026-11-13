#!/usr/bin/env bash
# Everything the workflow runs. Usage: ./ci.sh <output directory>     (needs Docker and Python 3)
set -uo pipefail
out="$(mkdir -p "$1" && cd "$1" && pwd)"
cd "$(dirname "$0")"
status=0
SDK="10.0.201"          # 12 March 2026
AS_OF="2026-04-25"      # the SQL Server image is the newest one built on or before this day

# A private SDK, so the build cannot roll forward to whatever newer .NET the machine carries.
root="$(mktemp -d)"
curl -fsSL -o "$root/dotnet-install.sh" https://dot.net/v1/dotnet-install.sh || exit 2
bash "$root/dotnet-install.sh" --version "$SDK" --install-dir "$root/sdk" --no-path > "$out/install.txt" 2>&1 || exit 2
export DOTNET_ROOT="$root/sdk" DOTNET_MULTILEVEL_LOOKUP=0 DOTNET_NOLOGO=1 DOTNET_CLI_TELEMETRY_OPTOUT=1
dotnet="$root/sdk/dotnet"

read -r tag built < <(python tools/pick_tag.py "$AS_OF" 2> "$out/tags.txt") || { cat "$out/tags.txt"; exit 2; }
IMAGE="mcr.microsoft.com/mssql/server:$tag"
docker pull -q "$IMAGE" > /dev/null || exit 2

# A throwaway password for a throwaway container. It is made here, lives in this shell and is never written to a file.
password="$(openssl rand -base64 24 | tr -d '/+=')aA1!"
docker run -d --name sql2025 -e ACCEPT_EULA=Y -e MSSQL_PID=Developer -e MSSQL_SA_PASSWORD="$password" \
  -p 127.0.0.1:14333:1433 --memory 6g "$IMAGE" > /dev/null || exit 2
# Encrypt is on; the certificate is the container's self-signed one, so it is trusted here and nowhere else.
export LAB_SQL_CONNECTION="Server=127.0.0.1,14333;User ID=sa;Password=$password;Encrypt=True;TrustServerCertificate=True;Connect Timeout=5"

{
  echo "image    $IMAGE"
  echo "built    $built"
  echo "digest   $(docker image inspect "$IMAGE" --format '{{index .RepoDigests 0}}' | cut -d@ -f2)"
  echo "size     $(docker image inspect "$IMAGE" --format '{{.Size}}' | awk '{printf "%.0f MB", $1/1e6}')"
  echo ".NET SDK $("$dotnet" --version)"
  echo "runner   $(nproc) vCPU, $(awk '/MemTotal/ {printf "%.0f GB", $2/1048576}' /proc/meminfo); container limited to 6 GB"
} | tee "$out/versions.txt"

echo "== the experiments"
"$dotnet" build src/Lab -c Release > "$out/build.txt" 2>&1 || { tail -n 30 "$out/build.txt"; exit 2; }
"$dotnet" run --project src/Lab -c Release --no-build -- sql "$out" 2>&1 | tee "$out/transcript.txt"; [ "${PIPESTATUS[0]}" -eq 0 ] || status=1

docker logs sql2025 2>&1 | grep -m1 -A3 "Microsoft SQL Server 2025" > "$out/server-banner.txt"
if grep -rqF "$password" "$out"; then echo "the password reached an output file"; rm -rf "${out:?}"/*; status=1; fi
docker rm -f sql2025 > /dev/null
exit $status
