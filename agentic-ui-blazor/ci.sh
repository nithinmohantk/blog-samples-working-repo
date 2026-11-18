#!/usr/bin/env bash
# Everything the workflow runs for this sample. Usage: ./ci.sh <output directory>   (needs the .NET 11 SDK and Python 3)
# Nothing here calls a model or a cloud service. The model is the scripted stand-in in src/Desk.Core.
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
pins = {"microsoft.aspnetcore.components.ai": "0.1.0-preview.1.26466.103", "agui.client": "1.0.1", "agui.server": "1.0.1", "microsoft.extensions.ai": "11.0.0", "bunit": "2.15.2", "microsoft.agents.ai.hosting.agui.aspnetcore": "1.28.0-preview.261106.1"}
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
  echo "== 0. probe (temporary)"
  dotnet build probe -c Release -v q 2>&1 | grep -E "error|Build succeeded" | sort -u | head -n 20
  dotnet run --project probe -c Release --no-build > "$out/probe-af.txt" 2>&1
  wc -l "$out/probe-af.txt"
  dotnet list probe package --include-transitive 2>/dev/null | grep -E "Agents|AGUI|Extensions.AI" | sed 's/  */ /g' | sort -u
} 2>&1 | tee "$out/00-probe.txt"

{
  echo "== 2. build"
  dotnet build tests/Desk.Tests -c Release -v q 2>&1 | grep -E "error|warn|Build succeeded|Warning\(s\)|Error\(s\)" | sort -u | head -n 60
  dotnet list tests/Desk.Tests package --include-transitive 2>/dev/null | grep -E "Components.AI |AGUI\.|Agents\.|Extensions.AI |Extensions.AI.Abstractions|bunit |Mvc.Testing|xunit " | sed 's/  */ /g' | sort -u
} 2>&1 | tee "$out/02-build.txt"
grep -q "Build succeeded" "$out/02-build.txt" || status=1

{
  echo "== 3. tests: the agent alone, the agent over AG-UI, the component in bUnit"
  rm -f "$out/wire-traces.txt" "$out/forged-approval.txt" "$out/stream-size.txt"
  DESK_OUT="$out" dotnet test tests/Desk.Tests -c Release --no-build --logger "console;verbosity=normal" 2>&1 | grep -E "^\s+(Passed|Failed|Skipped) |Error Message|Assert\.|Expected|Actual|Exception|   at Desk|Total tests|Passed:|Failed:|Test Run|Passed!|Failed!" | head -n 150
} 2>&1 | tee "$out/03-tests.txt"
grep -qE "Test Run Successful|Passed!" "$out/03-tests.txt" || status=1
{
  echo "== 3a. a forged approval, with the server-side check off and on"
  sort "$out/forged-approval.txt"
  echo "== 3b. size of the event stream"
  sort "$out/stream-size.txt"
} 2>&1 | tee "$out/03a-findings.txt"

{
  echo "== 4. browser: Chromium against the two running services"
  python -m pip install --quiet playwright && python -m playwright install --with-deps chromium > /dev/null 2>&1 || echo "playwright install failed"
  export ASPNETCORE_ENVIRONMENT=Development   # static web assets are served from the build output only in Development
  DESK_WIRE_LOG="$out/e2e-wire.jsonl" dotnet run --project src/Desk.Agent -c Release --no-build --no-launch-profile --urls http://127.0.0.1:5101 > "$out/agent.log" 2>&1 &
  agent=$!
  AGENT_URL=http://127.0.0.1:5101 dotnet run --project src/Desk.Web -c Release --no-build --no-launch-profile --urls http://127.0.0.1:5100 > "$out/web.log" 2>&1 &
  web=$!
  for i in $(seq 1 60); do curl -fsS http://127.0.0.1:5101/ledger > /dev/null 2>&1 && curl -fsS http://127.0.0.1:5100/ > /dev/null 2>&1 && break; sleep 1; done
  echo "-- one request with curl, as it arrives"
  curl -sN -X POST http://127.0.0.1:5101/agent -H "Content-Type: application/json" \
    -d '{"threadId":"t-curl","runId":"r-curl","messages":[{"id":"m1","role":"user","content":"Where is order O-1002?"}],"tools":[],"context":[]}' | tee "$out/05-raw-sse.txt" | cut -c1-220 | head -n 40
  echo "-- browser steps"
  python e2e/run.py http://127.0.0.1:5100 http://127.0.0.1:5101 "$out"
  browser=$?
  kill $web $agent 2>/dev/null
  exit $browser
} 2>&1 | tee "$out/04-browser.txt"
[ "${PIPESTATUS[0]}" -eq 0 ] || status=1

exit $status
