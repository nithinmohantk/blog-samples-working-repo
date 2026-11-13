#!/usr/bin/env bash
# Everything the workflow runs. Usage: ./ci.sh <output directory>     (needs Docker and Python 3; nothing is deployed)
set -uo pipefail
out="$(mkdir -p "$1" && cd "$1" && pwd)"
cd "$(dirname "$0")"
status=0
SDK="10.0.201"          # 12 March 2026, carries runtime 10.0.5
AS_OF="2026-04-11"      # base images are pinned to the newest dated tag on or before this day

dotnet_tag="$(python tools/pick_image.py lambda/dotnet 10 "$AS_OF")" || exit 2
provided_tag="$(python tools/pick_image.py lambda/provided al2023 "$AS_OF")" || exit 2
DOTNET_IMAGE="public.ecr.aws/lambda/dotnet:$dotnet_tag"
PROVIDED_IMAGE="public.ecr.aws/lambda/provided:$provided_tag"
docker pull -q "$DOTNET_IMAGE" > /dev/null && docker pull -q "$PROVIDED_IMAGE" > /dev/null && docker pull -q public.ecr.aws/amazonlinux/amazonlinux:2023 > /dev/null || exit 2
{
  echo "managed runtime image  $DOTNET_IMAGE"
  echo "  .NET runtime inside  $(docker run --rm --entrypoint /var/lang/bin/dotnet "$DOTNET_IMAGE" --list-runtimes | awk '/Microsoft.NETCore.App/ {print $2}')"
  echo "OS-only runtime image  $PROVIDED_IMAGE"
  echo "image sizes            $(docker image inspect "$DOTNET_IMAGE" --format '{{.Size}}' | awk '{printf "%.0f MB", $1/1e6}') and $(docker image inspect "$PROVIDED_IMAGE" --format '{{.Size}}' | awk '{printf "%.0f MB", $1/1e6}')"
  python --version; docker --version; nproc | sed 's/$/ vCPU on the runner/'
} | tee "$out/versions.txt"

# The managed runtime's start-up script, kept with the results because it decides how a package is started.
docker run --rm --entrypoint /bin/cat "$DOTNET_IMAGE" /var/runtime/bootstrap > "$out/managed-runtime-bootstrap.sh.txt"
echo "== build inside Amazon Linux 2023"
docker run --rm -v "$PWD:/work:ro" -v "$out:/out" public.ecr.aws/amazonlinux/amazonlinux:2023 bash /work/tools/build.sh "$SDK"; [ $? -eq 0 ] || status=1
cat "$out/build-versions.txt" >> "$out/versions.txt"
column -t -s "$(printf '\t')" "$out/build.tsv" | tee "$out/build.txt"
ls -l "$out/publish/aot" | awk 'NR>1 {printf "  aot/%s  %.1f MB\n", $9, $5/1e6}' | tee -a "$out/build.txt"

echo "== in the Lambda runtime emulator"
python -u tools/emulate.py "$out" "$DOTNET_IMAGE" "$PROVIDED_IMAGE" 2>&1 | tee "$out/emulator.txt"; [ "${PIPESTATUS[0]}" -eq 0 ] || status=1
sudo rm -rf "$out/publish" 2>/dev/null || rm -rf "$out/publish"
exit $status
