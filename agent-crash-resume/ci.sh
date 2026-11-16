#!/usr/bin/env bash
# Everything the workflow runs. Usage: ./ci.sh <output directory>     (needs Python 3.13)
# Three frameworks, three virtual environments: their dependency sets do not resolve together.
# The model is a local stand-in on 127.0.0.1; no hosted model and no cloud service is called.
set -uo pipefail
out="$(mkdir -p "$1" && cd "$1" && pwd)"
cd "$(dirname "$0")"
AS_OF="2026-03-23T00:00:00Z"   # unpinned dependencies are resolved as they stood on this day
work="$(mktemp -d)"
failed=0

python -m pip install --quiet uv || exit 2
for name in langgraph agent-framework adk; do
  python -m uv venv --quiet "$work/$name" && python -m uv pip install --quiet --python "$work/$name/bin/python" --exclude-newer "$AS_OF" -r "requirements/$name.txt" || exit 2
done

{
  echo "== 1. versions"
  python --version
  "$work/langgraph/bin/python" -c "import importlib.metadata as m; print(*[f'{p} {m.version(p)}' for p in ('langgraph', 'langchain', 'langchain-openai', 'langgraph-checkpoint-sqlite', 'langgraph-checkpoint')], sep='\n')"
  "$work/agent-framework/bin/python" -c "import importlib.metadata as m; print(*[f'{p} {m.version(p)}' for p in ('agent-framework-core', 'openai')], sep='\n')"
  "$work/adk/bin/python" -c "import importlib.metadata as m; print(*[f'{p} {m.version(p)}' for p in ('google-adk', 'google-genai')], sep='\n')"
  uname -srm
} 2>&1 | tee "$out/01-versions.txt"

{
  echo "== 2. unit tests for the stand-in and the tools"
  python tests/run.py 2>&1 | tail -n 4
} 2>&1 | tee "$out/02-unit-tests.txt"
grep -q "^OK" "$out/02-unit-tests.txt" || failed=1

{
  echo "== 3. crash, recover, count"
  python lab/run.py "$out" --langgraph "$work/langgraph/bin/python" --agent-framework "$work/agent-framework/bin/python" --adk "$work/adk/bin/python"
} 2>&1 | tee "$out/03-crash-resume.txt"
[ "${PIPESTATUS[0]}" -eq 0 ] || failed=1

exit $failed
