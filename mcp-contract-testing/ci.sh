#!/usr/bin/env bash
# Everything the workflow runs. Usage: ./ci.sh <output directory>     (needs Python 3.13)
# Nothing leaves the machine: every MCP server here is a local process on stdio or 127.0.0.1.
set -uo pipefail
out="$(mkdir -p "$1" && cd "$1" && pwd)"
cd "$(dirname "$0")"
AS_OF="2026-11-04T00:00:00Z"   # unpinned dependencies are resolved as they stood on this day
log() { printf '\n$ %s\n' "$*"; }

python -m pip install --quiet uv || exit 2
envs="$(mktemp -d)"
make_env() { # name, exclude-newer date, requirement...
  local name="$1" as_of="$2"; shift 2
  python -m uv venv --quiet "$envs/$name" && python -m uv pip install --quiet --python "$envs/$name/bin/python" --exclude-newer "$as_of" "$@"
}
make_env main "$AS_OF" -r requirements.txt || exit 2
py="$envs/main/bin/python"
failed=0

{
  echo "== 1. versions"
  "$py" --version
  "$py" -c "import importlib.metadata as m; print(*[f'{p} {m.version(p)}' for p in ('mcp', 'pydantic', 'jsonschema', 'starlette', 'anyio')], sep='\n')"
  "$py" -c "from mcp_types.version import KNOWN_PROTOCOL_VERSIONS as k; print('protocol revisions known to the SDK:', ', '.join(k))"
  uname -srm; nproc | sed 's/$/ vCPU/'
} 2>&1 | tee "$out/01-versions.txt"

{
  echo "== 2. unit tests for the compatibility rules"
  log "python tests/run.py"
  "$py" tests/run.py 2>&1 | tail -n 4
} 2>&1 | tee "$out/02-unit-tests.txt"
grep -q "^OK" "$out/02-unit-tests.txt" || failed=1

{
  echo "== 3. snapshot: stdio, then Streamable HTTP, then compare with the committed file"
  log "python contract/snapshot.py --stdio 'python server/app.py' --out live-stdio.json"
  "$py" contract/snapshot.py --stdio "$py server/app.py" --out "$out/live-stdio.json" 2>&1 | sed "s|$out/||"
  "$py" server/app.py http 8765 > "$out/server-http.log" 2>&1 & http=$!
  for i in $(seq 1 100); do (exec 3<>/dev/tcp/127.0.0.1/8765) 2>/dev/null && break; sleep 0.1; done
  log "python contract/snapshot.py --url http://127.0.0.1:8765/mcp --out live-http.json"
  "$py" contract/snapshot.py --url http://127.0.0.1:8765/mcp --out "$out/live-http.json" 2>&1 | sed "s|$out/||"
  kill "$http" 2>/dev/null
  log "sha256sum live-stdio.json live-http.json contract/mcp-contract.json"
  sha256sum "$out/live-stdio.json" "$out/live-http.json" contract/mcp-contract.json | sed "s|$out/||"
  cmp -s "$out/live-stdio.json" contract/mcp-contract.json && cmp -s "$out/live-http.json" contract/mcp-contract.json \
    && echo "all three are byte-identical" || { echo "SNAPSHOTS DIFFER"; exit 1; }
  log "wc -c contract/mcp-contract.json"; wc -c < contract/mcp-contract.json | sed 's/$/ bytes/'
} 2>&1 | tee "$out/03-snapshot.txt"
[ "${PIPESTATUS[0]}" -eq 0 ] || failed=1

{
  echo "== 4. replay the recorded calls against the unchanged server"
  log "python contract/replay.py --stdio 'python server/app.py' --contract contract/mcp-contract.json"
  "$py" contract/replay.py --stdio "$py server/app.py" --contract contract/mcp-contract.json --json "$out/replay-baseline.json" 2> "$out/replay-baseline.stderr.txt"
} 2>&1 | tee "$out/04-replay.txt"
[ "${PIPESTATUS[0]}" -eq 0 ] || failed=1

gate() { # description, expected exit code, gate arguments...
  local what="$1" expected="$2"; shift 2
  log "gate: $what"
  "$py" contract/gate.py "$@"; local code=$?
  echo "exit code $code (expected $expected)"
  [ "$code" -eq "$expected" ] || return 1
}
{
  echo "== 5. the gate, in the five situations a pull request can be in"
  work="$(mktemp -d)"; ok=0
  snap() { "$py" contract/snapshot.py --stdio "$py lab/variants.py $1" --out "$work/$2" 2> /dev/null; }
  snap baseline live.json; snap v04 v04.json; snap v06 v06.json; snap v18 v18.json
  "$py" contract/snapshot.py --stdio "$py lab/variants.py v06 2.0.0" --out "$work/v06-major.json" 2> /dev/null
  gate "nothing changed" 0 --base contract/mcp-contract.json --head contract/mcp-contract.json --live "$work/live.json" || ok=1
  gate "the code changed and the snapshot was not regenerated" 2 --base contract/mcp-contract.json --head contract/mcp-contract.json --live "$work/v04.json" || ok=1
  gate "a description changed (review only)" 0 --base contract/mcp-contract.json --head "$work/v18.json" --live "$work/v18.json" || ok=1
  gate "a constraint was tightened, version still 1.4.0" 1 --base contract/mcp-contract.json --head "$work/v06.json" --live "$work/v06.json" || ok=1
  gate "the same change released as 2.0.0" 0 --base contract/mcp-contract.json --head "$work/v06-major.json" --live "$work/v06-major.json" || ok=1
  exit $ok
} 2>&1 | tee "$out/05-gate.txt"
[ "${PIPESTATUS[0]}" -eq 0 ] || failed=1

{
  echo "== 6. twenty-one changes: what the gate says, and what a client that was not told sees"
  "$py" lab/run_variants.py "$out" 2> "$out/variants.stderr.txt"
} 2>&1 | tee "$out/06-variants.txt"
[ "${PIPESTATUS[0]}" -eq 0 ] || failed=1

{
  echo "== 7. the same server file under other SDK installations"
  make_env sdk-1.9.4-fresh "$AS_OF" "mcp==1.9.4"
  make_env sdk-1.9.4-2025 "2025-06-20T00:00:00Z" "mcp==1.9.4"
  make_env sdk-1.26.0 "$AS_OF" "mcp==1.26.0"
  make_env sdk-1.30.0 "$AS_OF" "mcp==1.30.0"
  "$py" lab/sdk_drift.py "$out" \
    "1.9.4-with-current-dependencies=$envs/sdk-1.9.4-fresh/bin/python" \
    "1.9.4-with-june-2025-dependencies=$envs/sdk-1.9.4-2025/bin/python" \
    "1.26.0=$envs/sdk-1.26.0/bin/python" "1.30.0=$envs/sdk-1.30.0/bin/python" "2.3.0=$py" 2> "$out/sdk-drift.stderr.txt" | sed "s|$envs/[^ ]*/site-packages/||g"
} 2>&1 | tee "$out/07-sdk-drift.txt"
[ "${PIPESTATUS[0]}" -eq 0 ] || failed=1

{
  echo "== 8. what the gate costs a build"
  for step in "snapshot|$py contract/snapshot.py --stdio \"$py server/app.py\" --out $out/timing.json" \
              "gate|$py contract/gate.py --base contract/mcp-contract.json --head contract/mcp-contract.json --live $out/timing.json" \
              "replay|$py contract/replay.py --stdio \"$py server/app.py\" --contract contract/mcp-contract.json"; do
    name="${step%%|*}"; command="${step#*|}"
    began="$(date +%s.%N)"; eval "$command" > /dev/null 2>&1
    printf '%-9s %.2f s\n' "$name" "$(echo "$(date +%s.%N) - $began" | bc)"
  done
  rm -f "$out/timing.json"
} 2>&1 | tee "$out/08-timing.txt"

sed -i "s|$envs/[a-z0-9.-]*/|<env>/|g" "$out"/*.txt "$out"/*.json 2>/dev/null
exit $failed
