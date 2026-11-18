#!/usr/bin/env bash
# Runs inside an Amazon Linux 2023 container, so the Native AOT executable links against the C library that
# provided.al2023 has. Publishes the function five ways into /out and writes sizes and times to /out/build.tsv.
set -uo pipefail
SDK="$1"
export DOTNET_NOLOGO=1 DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1
dnf install -y -q clang gcc zlib-devel tar gzip findutils zip > /dev/null 2>&1 || exit 2
curl -fsSL -o /tmp/dotnet-install.sh https://dot.net/v1/dotnet-install.sh && bash /tmp/dotnet-install.sh --version "$SDK" --install-dir /opt/dotnet --no-path > /out/install.txt 2>&1 || exit 2
export DOTNET_ROOT=/opt/dotnet PATH=/opt/dotnet:$PATH
cp -r /work /build && cd /build
{ echo "SDK $(dotnet --version), runtime $(dotnet --list-runtimes | awk '/Microsoft.NETCore.App/ {print $2}')"; grep PRETTY_NAME /etc/os-release | cut -d'"' -f2; clang --version | head -n 1; } | tee /out/build-versions.txt

status=0
echo "== the handler on its own"
dotnet run --project tests/SelfTest -c Release 2>&1 | grep -v "^$" | tee /out/selftest.txt; [ "${PIPESTATUS[0]}" -eq 0 ] || status=1

printf 'name\tflavour\treflection\tseconds\tfiles\tfolder_bytes\tzip_bytes\ttrim_warnings\n' > /out/build.tsv
publish() { # name flavour reflection
  rm -rf src/Quotes.Function/bin src/Quotes.Function/obj
  local began; began=$(date +%s%N)
  dotnet publish src/Quotes.Function -c Release -r linux-x64 --self-contained "$([ "$2" = aot ] && echo true || echo false)" \
    -p:Flavour="$2" -p:ReflectionJson="$3" -p:DebugType=none -o "/out/publish/$1" > "/out/publish-$1.log" 2>&1 || { echo "publish $1 FAILED"; tail -n 20 "/out/publish-$1.log"; status=1; return; }
  local seconds; seconds=$(( ($(date +%s%N) - began) / 1000000000 ))
  find "/out/publish/$1" -name '*.dbg' -delete
  ( cd "/out/publish/$1" && zip -q -r "/out/$1.zip" . )
  # IL2026 and IL3050 are the compiler saying "this needs reflection that will not be there".
  local warnings; warnings=$(grep -oE "warning IL(2026|3050)" "/out/publish-$1.log" | sort | uniq -c | awk '{printf "%s x%s ", $3, $1}')
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$1" "$2" "$3" "$seconds" "$(find "/out/publish/$1" -type f | wc -l)" "$(du -sb "/out/publish/$1" | cut -f1)" "$(stat -c %s "/out/$1.zip")" "${warnings:-none}" >> /out/build.tsv
  echo "published $1 in $seconds s"
}
echo "== publishing"
publish jit jit false
publish r2r r2r false
publish aot aot false
publish jit-reflection jit true
publish aot-reflection aot true
rm -f /out/*.zip
chmod -R a+rwX /out
exit $status
