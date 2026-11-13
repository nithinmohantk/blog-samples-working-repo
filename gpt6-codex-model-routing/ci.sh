#!/usr/bin/env bash
# Everything the workflow runs. Usage: ./ci.sh <output directory>     (needs Python 3.12 or later)
set -uo pipefail
out="$(mkdir -p "$1" && cd "$1" && pwd)"
cd "$(dirname "$0")"
AS_OF="2026-09-26T00:00:00Z"   # Python packages are resolved as they stood on this day
CODEX_TAG="rust-v0.157.1"      # Codex CLI 0.157.1, released 26 September 2026
SCHEMA_SHA256="17fbda7e71603aa6a83e986608f2e13c27ea46ce1a4b889196ba81a07c39d907"

# The configuration schema is a file in the Codex repository. Only that file is fetched; the CLI is not installed.
schema="$(mktemp -d)/config.schema.json"
curl -fsSL -o "$schema" "https://raw.githubusercontent.com/openai/codex/$CODEX_TAG/codex-rs/core/config.schema.json" || exit 2
actual="$(sha256sum "$schema" | cut -d' ' -f1)"
if [ "$actual" != "$SCHEMA_SHA256" ]; then echo "schema checksum mismatch: $actual"; exit 2; fi

python -m pip install --quiet uv || exit 2
venv="$(mktemp -d)/venv"
python -m uv venv --quiet "$venv" || exit 2
python -m uv pip install --quiet --python "$venv/bin/python" --exclude-newer "$AS_OF" jsonschema || exit 2
{
  "$venv/bin/python" --version
  "$venv/bin/python" -c "from importlib.metadata import version; print('jsonschema', version('jsonschema'))"
  echo "Codex configuration schema at $CODEX_TAG, sha256 $actual"
} | tee "$out/versions.txt"
"$venv/bin/python" tests/run.py "$out" "$schema" 2>&1 | tee "$out/run.txt"
exit "${PIPESTATUS[0]}"
