#!/usr/bin/env bash
# Everything the workflow runs for this sample. Usage: ./ci.sh <output directory>   (needs the .NET 11 SDK and Python 3)
# Nothing here calls a model, an identity provider or a cloud service. The model is the scripted stand-in
# in src/Desk.Core, and sign-in is the lab page in src/Desk.Bff.
set -uo pipefail
out="$(mkdir -p "$1" && cd "$1" && pwd)"
cd "$(dirname "$0")"
status=0

{
  echo "== 1. versions"
  dotnet --version
  dotnet --list-runtimes | grep -E "AspNetCore.App 11|NETCore.App 11"
  uname -srm
  dotnet restore tests/Desk.Tests -v q > /dev/null 2>&1
  echo "-- target frameworks inside the packages, and the day each version was published"
  python3 - <<'PY'
import glob, gzip, json, os, urllib.request
pins = {"microsoft.aspnetcore.components.ai": "0.1.0-preview.1.26466.103", "microsoft.aspnetcore.components.webassembly": "11.0.0", "microsoft.aspnetcore.authentication.jwtbearer": "11.0.0", "agui.client": "1.0.1", "agui.server": "1.0.1", "microsoft.extensions.ai": "11.0.0"}
for name, version in pins.items():
    frameworks = sorted(os.path.basename(p) for p in glob.glob(os.path.expanduser(f"~/.nuget/packages/{name}/{version}/lib/*")))
    published = "unknown"
    try:
        raw = urllib.request.urlopen(f"https://api.nuget.org/v3/registration5-gz-semver2/{name}/{version}.json", timeout=30).read()
        leaf = json.loads(gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw)
        published = leaf.get("published", "unknown")[:10]
    except Exception as error:
        published = f"lookup failed: {error}"
    print(f"{name} {version}: lib {frameworks}; published {published}")
PY
} 2>&1 | tee "$out/01-versions.txt"

{
  echo "== 2. build"
  dotnet build tests/Desk.Tests -c Release -v q 2>&1 | grep -E "error|warn|Build succeeded|Warning\(s\)|Error\(s\)" | sort -u | head -n 60
  dotnet list tests/Desk.Tests package --include-transitive 2>/dev/null | grep -E "Components.AI |Components.WebAssembly|JwtBearer|IdentityModel.JsonWebTokens|AGUI\.|Extensions.AI |Mvc.Testing|xunit " | sed 's/  */ /g' | sort -u
} 2>&1 | tee "$out/02-build.txt"
grep -q "Build succeeded" "$out/02-build.txt" || status=1

{
  echo "== 3. tests: the agent service with tokens, then the web host in front of it"
  rm -f "$out/auth-results.txt"
  DESK_OUT="$out" dotnet test tests/Desk.Tests -c Release --no-build --logger "console;verbosity=normal" 2>&1 | grep -E "^\s+(Passed|Failed|Skipped) |Error Message|Assert\.|Expected|Actual|Exception|   at Desk|Total tests|Passed:|Failed:|Test Run|Passed!|Failed!" | head -n 150
  echo "-- what the tests recorded"
  sort "$out/auth-results.txt" 2>/dev/null
} 2>&1 | tee "$out/03-tests.txt"
grep -qE "Test Run Successful|Passed!" "$out/03-tests.txt" || status=1

publish="${RUNNER_TEMP:-/tmp}/desk-wasm-publish"
{
  echo "== 4. publish, as it would be deployed: the WebAssembly app is trimmed and compressed"
  rm -rf "$publish"
  dotnet publish src/Desk.Bff -c Release -o "$publish/bff" 2>&1 | grep -E "error|warning|->" | sed "s#$PWD/##g; s#$publish#<publish>#g" | sort -u | head -n 40
  dotnet publish src/Desk.Agent -c Release -o "$publish/agent" 2>&1 | grep -E "error|warning" | sort -u | head -n 20
  python3 - "$publish/bff/wwwroot" <<'PY'
import os, sys
root = sys.argv[1]
plain = br = gz = files = 0
biggest = []
for folder, _, names in os.walk(os.path.join(root, "_framework")):
    for name in names:
        size = os.path.getsize(os.path.join(folder, name))
        if name.endswith(".br"):
            br += size
            biggest.append((size, name))
        elif name.endswith(".gz"):
            gz += size
        else:
            plain += size
            files += 1
print(f"_framework: {files} files, {plain / 1048576:.2f} MiB as built, {br / 1048576:.2f} MiB as Brotli, {gz / 1048576:.2f} MiB as gzip")
for size, name in sorted(biggest, reverse=True)[:12]:
    print(f"  {size / 1024:8.0f} KiB  {name}")
PY
} 2>&1 | tee "$out/04-publish.txt"
[ -f "$publish/bff/Desk.Bff.dll" ] || status=1

{
  echo "== 5. browser: Chromium against the published web host and the agent service"
  python -m pip install --quiet playwright && python -m playwright install --with-deps chromium > /dev/null 2>&1 || echo "playwright install failed"
  python -c "import playwright, importlib.metadata as m; print('playwright', m.version('playwright'))"
  (cd "$publish/agent" && DESK_LAB=true DESK_WIRE_LOG="$out/e2e-wire.jsonl" dotnet Desk.Agent.dll --urls http://127.0.0.1:5111 > "$out/agent.log" 2>&1) &
  (cd "$publish/bff" && DESK_LAB=true AGENT_URL=http://127.0.0.1:5111 dotnet Desk.Bff.dll --urls http://127.0.0.1:5110 > "$out/bff.log" 2>&1) &
  for i in $(seq 1 60); do curl -fsS http://127.0.0.1:5111/ledger > /dev/null 2>&1 && curl -fsS http://127.0.0.1:5110/signin > /dev/null 2>&1 && break; sleep 1; done
  echo "-- with curl: no session, then the agent service called directly without a token"
  curl -s -o /dev/null -w "GET  web host /            HTTP %{http_code} -> %{redirect_url}\n" http://127.0.0.1:5110/
  curl -s -o /dev/null -w "POST web host /agent       HTTP %{http_code}\n" -X POST -H "Content-Type: application/json" -H "X-Desk-Client: 1" -d '{}' http://127.0.0.1:5110/agent
  curl -s -o /dev/null -w "POST agent service /agent  HTTP %{http_code}\n" -X POST -H "Content-Type: application/json" -d '{}' http://127.0.0.1:5111/agent
  curl -s -o /dev/null -w "GET  web host /_framework/blazor.web.js  HTTP %{http_code}, %{size_download} bytes, no session needed\n" -H "Accept-Encoding: br" http://127.0.0.1:5110/_framework/blazor.web.js
  echo "-- browser steps"
  python e2e/run.py http://127.0.0.1:5110 http://127.0.0.1:5111 "$out"
  browser=$?
  echo "-- browser console, errors and warnings"
  head -n 20 "$out/browser-console.txt" 2>/dev/null
  pkill -f "Desk.Agent.dll" ; pkill -f "Desk.Bff.dll"
  exit $browser
} 2>&1 | tee "$out/05-browser.txt"
[ "${PIPESTATUS[0]}" -eq 0 ] || status=1

exit $status
