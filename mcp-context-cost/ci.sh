#!/usr/bin/env bash
# Everything the workflow runs. Usage: ./ci.sh <output directory>     (needs Python 3.13, Node.js 22, and gh with GH_TOKEN for one download)
# Each MCP server is installed at a pinned version, started as a local process on stdio, and asked for its
# tool listing. No tool is called, so no server reads a file, opens a browser or reaches the network.
set -uo pipefail
out="$(mkdir -p "$1" && cd "$1" && pwd)"
cd "$(dirname "$0")"
AS_OF="2026-03-04"   # unpinned dependencies are resolved as they stood on this day
work="$(mktemp -d)"
failed=0

python -m pip install --quiet uv || exit 2
python -m uv venv --quiet "$work/env" && python -m uv pip install --quiet --python "$work/env/bin/python" --exclude-newer "${AS_OF}T00:00:00Z" -r requirements.txt || exit 2
py="$work/env/bin/python"

# npm servers, at the versions in servers.json, with their own dependencies as of the same day
packages="$("$py" -c "import json; print(*[s['package'] + '@' + s['version'] for s in json.load(open('servers.json'))['servers'] if s['source'] == 'npm'])")"
mkdir -p "$work/node" && ( cd "$work/node" && npm init -y > /dev/null && npm install --silent --no-audit --no-fund --before="$AS_OF" $packages ) \
  || echo "npm install failed; the npm servers will be reported as not started"

# the GitHub MCP server ships as a release binary: take the newest release published before the cut-off date
github_binary=""; github_version=""
if command -v gh > /dev/null && [ -n "${GH_TOKEN:-}" ]; then
  github_version="$(gh api 'repos/github/github-mcp-server/releases?per_page=100' \
    --jq "[.[] | select(.prerelease == false and .draft == false and .published_at < \"${AS_OF}\")] | sort_by(.published_at) | last | .tag_name" 2> /dev/null)"
  if [ -n "$github_version" ] && gh release download "$github_version" --repo github/github-mcp-server --pattern '*Linux_x86_64.tar.gz' --dir "$work/gh" 2> /dev/null; then
    tar -xzf "$work"/gh/*.tar.gz -C "$work/gh" && github_binary="$work/gh/github-mcp-server"
  fi
fi

{
  echo "== 1. versions"
  "$py" --version; node --version | sed 's/^/node /'
  "$py" -c "import importlib.metadata as m; print(*[f'{p} {m.version(p)}' for p in ('mcp', 'tiktoken', 'mcp-server-git', 'mcp-server-time', 'mcp-server-fetch')], sep='\n')"
  ( cd "$work/node" && npm ls --depth=0 2> /dev/null | sed -n '2,$p' | sed 's/^[^@a-z]*//' | grep . )
  echo "github-mcp-server ${github_version:-not downloaded}"
  uname -srm
} 2>&1 | tee "$out/01-versions.txt"

{
  echo "== 2. unit tests"
  "$py" tests/run.py 2>&1 | tail -n 4
} 2>&1 | tee "$out/02-unit-tests.txt"
grep -q "^OK" "$out/02-unit-tests.txt" || failed=1

{
  echo "== 3. tool listings"
  "$py" lab/collect.py "$out" --node "$work/node" --bin "$work/env/bin" --github-binary "$github_binary" --github-version "$github_version"
} 2>&1 | tee "$out/03-listings.txt"
[ "${PIPESTATUS[0]}" -eq 0 ] || failed=1

{
  echo "== 4. what the listings cost"
  "$py" lab/analyse.py "$out"
} 2>&1 | tee "$out/04-context-cost.txt"
[ "${PIPESTATUS[0]}" -eq 0 ] || failed=1

sed -i "s|$work|<work>|g" "$out"/*.txt "$out"/*.json 2> /dev/null
exit $failed
