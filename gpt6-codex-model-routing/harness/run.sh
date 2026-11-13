#!/usr/bin/env bash
# Runs the Codex CLI against the local stand-in and records what it sends. Usage: run.sh <output dir> <python>
# The CLI is given a fake key for a provider that exists only on this machine. It cannot reach a real model.
set -uo pipefail
out="$1"; python="$2"
here="$(cd "$(dirname "$0")" && pwd)"
CODEX_VERSION="0.157.1"
work="$(mktemp -d)"

npm install --silent --prefix "$work/cli" "@openai/codex@$CODEX_VERSION" > "$out/npm.txt" 2>&1 || { tail -n 20 "$out/npm.txt"; exit 2; }
codex="$work/cli/node_modules/.bin/codex"
"$codex" --version | tee "$out/codex-version.txt"
"$codex" exec --help > "$out/codex-exec-help.txt" 2>&1
"$codex" --help > "$out/codex-help.txt" 2>&1

# A small repository for the agent to look at.
repo="$work/repo"; mkdir -p "$repo/src"
for i in 1 2 3 4 5 6; do
  "$python" - "$repo/src/module_$i.py" "$i" <<'PY'
import sys
path, n = sys.argv[1], int(sys.argv[2])
open(path, "w").write("".join(f"def function_{n}_{k}(value):\n    \"\"\"Returns value plus {k}, for module {n}.\"\"\"\n    return value + {k}\n\n\n" for k in range(120)))
PY
done
printf '# Notes\n\nA test repository. Nothing here is real.\n' > "$repo/NOTES.md"
git -C "$repo" init -q && git -C "$repo" -c user.name=t -c user.email=t@example.invalid add -A && git -C "$repo" -c user.name=t -c user.email=t@example.invalid commit -q -m init

scenario() { # name, script json, extra config lines, codex exec arguments...
  local name="$1" script="$2" extra="$3"; shift 3
  local home="$work/home-$name"; mkdir -p "$home"; cp "$here"/../codex/*.config.toml "$home/"
  echo "$script" > "$work/$name.json"
  rm -f "$work/port"
  "$python" "$here/standin.py" "$work/port" "$out/requests-$name.jsonl" "$work/$name.json" &
  local server=$!
  for _ in $(seq 1 50); do [ -s "$work/port" ] && break; sleep 0.1; done
  # The example configuration from the article, plus a provider that points at the stand-in.
  { printf 'model_provider = "standin"\n%s\n' "$extra"; cat "$here/../codex/config.toml"
    printf '\n[model_providers.standin]\nname = "Local stand-in"\nbase_url = "http://127.0.0.1:%s/v1"\nenv_key = "STANDIN_KEY"\nwire_api = "responses"\n' "$(cat "$work/port")"; } > "$home/config.toml"
  echo "== $name: codex exec $*"
  ( cd "$repo" && CODEX_HOME="$home" STANDIN_KEY="not-a-real-key" timeout 180 "$codex" exec "$@" "Read the notes and the modules, then say done." < /dev/null ) > "$out/codex-$name.txt" 2>&1
  echo "   exit code $? ; $(grep -c '"request"' "$out/requests-$name.jsonl" 2>/dev/null || echo 0) model requests"
  kill "$server" 2>/dev/null; wait "$server" 2>/dev/null
}

six='[{"shell":"cat NOTES.md"},{"shell":"cat src/module_1.py"},{"shell":"cat src/module_2.py"},{"shell":"cat src/module_3.py"},{"shell":"cat src/module_4.py"},{"shell":"cat src/module_5.py"},{"message":"done"}]'
two='[{"shell":"cat NOTES.md"},{"message":"done"}]'
scenario default "$six" "" --sandbox read-only
scenario deep "$two" "" --sandbox read-only --profile deep
scenario ci "$two" "" --profile ci
scenario compact "$six" "" --sandbox read-only -c model_auto_compact_token_limit=20000
"$codex" exec review --help > "$out/codex-review-help.txt" 2>&1
"$python" "$here/report.py" "$out" 2>&1 | tee "$out/harness.txt"
