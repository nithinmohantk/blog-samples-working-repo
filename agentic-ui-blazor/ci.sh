#!/usr/bin/env bash
# Everything the workflow runs for this sample. Usage: ./ci.sh <output directory>
set -uo pipefail
out="$(mkdir -p "$1" && cd "$1" && pwd)"
cd "$(dirname "$0")"
status=0
{
  echo "== versions"
  dotnet --version
  for id in Microsoft.AspNetCore.Components.AI AGUI.Client AGUI.Server Microsoft.Agents.AI.Hosting.AGUI.AspNetCore Microsoft.Agents.AI Microsoft.Extensions.AI bunit; do
    dotnet package search "$id" --exact-match --prerelease --format json 2>/dev/null | python3 -c "
import json, sys
found = [p for s in json.load(sys.stdin)['searchResult'] for p in s['packages']]
print('$id', [p.get('version') or p.get('latestVersion') for p in found][-4:])" || echo "$id: search failed"
  done
} 2>&1 | tee "$out/01-versions.txt"
{
  echo "== probe"
  dotnet build probe -c Release -v q 2>&1 | tail -n 25
  dotnet list probe package --include-transitive 2>&1 | grep -i -E "components.ai|agui|agents|extensions.ai|bunit|>" | head -n 60
  for id in microsoft.aspnetcore.components.ai agui.client agui.server microsoft.agents.ai.hosting.agui.aspnetcore bunit; do echo "$id: $(ls -d ~/.nuget/packages/$id/*/lib/* 2>/dev/null | sed 's#.*/packages/##' | tr '\n' ' ')"; done
  dotnet run --project probe -c Release --no-build > "$out/probe-api.txt" 2>&1 || status=1
  wc -l "$out/probe-api.txt"
} 2>&1 | tee "$out/02-probe.txt"
exit $status
