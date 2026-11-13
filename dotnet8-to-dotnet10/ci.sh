#!/usr/bin/env bash
# Installs the two SDKs into private directories, so nothing rolls forward to a newer runtime on the machine,
# then runs the checks. Usage: ./ci.sh <output directory>
set -uo pipefail
out="$(mkdir -p "$1" && cd "$1" && pwd)"
cd "$(dirname "$0")"
SDK8="8.0.417"; RUNTIME8="8.0.23"     # 13 January 2026
SDK10="10.0.102"                      # 13 January 2026, carries runtime 10.0.2
root="$(mktemp -d)"
curl -fsSL -o "$root/dotnet-install.sh" https://dot.net/v1/dotnet-install.sh || exit 2
bash "$root/dotnet-install.sh" --version "$SDK8" --install-dir "$root/sdk8" --no-path > "$out/install.txt" 2>&1 || exit 2
bash "$root/dotnet-install.sh" --version "$SDK10" --install-dir "$root/sdk10" --no-path >> "$out/install.txt" 2>&1 || exit 2
bash "$root/dotnet-install.sh" --runtime aspnetcore --version "$RUNTIME8" --install-dir "$root/sdk10" --no-path >> "$out/install.txt" 2>&1 || exit 2
{ for d in sdk8 sdk10; do echo "[$d]"; DOTNET_ROOT="$root/$d" DOTNET_MULTILEVEL_LOOKUP=0 "$root/$d/dotnet" --list-sdks; DOTNET_ROOT="$root/$d" DOTNET_MULTILEVEL_LOOKUP=0 "$root/$d/dotnet" --list-runtimes | grep -v WindowsDesktop; done; } | sed "s|$root/||" | tee "$out/versions.txt"

status=0
python -u upgrade_check.py "$root/sdk8" "$root/sdk10" "$out" recorded.json 2>&1 | tee "$out/upgrade-check.txt"; [ "${PIPESTATUS[0]}" -eq 0 ] || status=1

echo "== container base images" | tee "$out/images.txt"
for tag in 8.0 10.0; do
  printf 'aspnet:%s  ' "$tag" | tee -a "$out/images.txt"
  docker run --rm --entrypoint /bin/sh "mcr.microsoft.com/dotnet/aspnet:$tag" -c '. /etc/os-release; echo "$PRETTY_NAME"' 2>/dev/null | tee -a "$out/images.txt" || status=1
done
exit $status
