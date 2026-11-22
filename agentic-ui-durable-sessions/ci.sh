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
  python3 - <<'PY'
import glob, gzip, json, os, urllib.request
pins = {"microsoft.aspnetcore.components.ai": "0.1.0-preview.1.26466.103", "agui.client": "1.0.1", "agui.server": "1.0.1", "microsoft.extensions.ai": "11.0.0", "microsoft.data.sqlite": "11.0.0"}
for name, version in pins.items():
    published = "unknown"
    try:
        raw = urllib.request.urlopen(f"https://api.nuget.org/v3/registration5-gz-semver2/{name}/{version}.json", timeout=30).read()
        leaf = json.loads(gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw)
        published = leaf.get("published", "unknown")[:10]
    except Exception as error:
        published = f"lookup failed: {error}"
    print(f"{name} {version}: published {published}")
PY
} 2>&1 | tee "$out/01-versions.txt"

{
  echo "== 2. build"
  dotnet build tests/Desk.Tests -c Release -v q 2>&1 | grep -E "error|warn|Build succeeded|Warning\(s\)|Error\(s\)" | sort -u | head -n 60
} 2>&1 | tee "$out/02-build.txt"
grep -q "Build succeeded" "$out/02-build.txt" || status=1

{
  echo "== 3. tests: the UI agent with a journal, against the agent service on an in-memory server"
  rm -f "$out/restore-results.txt"
  DESK_OUT="$out" timeout 600 dotnet test tests/Desk.Tests -c Release --no-build --logger "console;verbosity=normal" 2>&1 | grep -E "^\s+(Passed|Failed|Skipped) |Error Message|Assert\.|Expected|Actual|Exception|   at Desk|Total tests|Passed:|Failed:|Test Run|Passed!|Failed!" | head -n 150
  echo "-- what the tests recorded"
  sort "$out/restore-results.txt" 2>/dev/null
} 2>&1 | tee "$out/03-tests.txt"
grep -qE "Test Run Successful|Passed!" "$out/03-tests.txt" || status=1

{
  echo "== 4. browser: reload, restart, a second tab"
  python -m pip install --quiet playwright && python -m playwright install --with-deps chromium > /dev/null 2>&1 || echo "playwright install failed"
  rm -rf "$out/data" "$out/e2e-wire.jsonl"
  timeout 900 python e2e/run.py "$out"
  browser=$?
  echo "-- what is on disk afterwards"
  python3 - "$out/data" <<'PY'
import os, sqlite3, sys
folder = sys.argv[1]
for name in sorted(os.listdir(folder)):
    print(f"{name}: {os.path.getsize(os.path.join(folder, name))} bytes")
db = sqlite3.connect(os.path.join(folder, "conversations.db"))
print("conversations:", db.execute("select count(distinct thread) from journal").fetchone()[0], "| journal rows:", db.execute("select count(*) from journal").fetchone()[0], "| state rows:", db.execute("select count(*) from state").fetchone()[0])
print("pending approvals left:", sqlite3.connect(os.path.join(folder, "approvals.db")).execute("select count(*) from approvals").fetchone()[0])
PY
  rm -rf "$out/data"
  exit $browser
} 2>&1 | tee "$out/04-browser.txt"
[ "${PIPESTATUS[0]}" -eq 0 ] || status=1

exit $status
