#!/usr/bin/env bash
# Installs pinned versions, starts the six servers, runs the probe and graphql-http's audits,
# runs the client tests, and stops the servers. Results go to results/.
set -euo pipefail
cd "$(dirname "$0")"
(cd servers/node && npm ci --silent)
if command -v uv >/dev/null; then
  [ -d servers/python/.venv ] || uv venv -q servers/python/.venv
  uv pip install -q --python servers/python/.venv/bin/python -r requirements.txt
else
  [ -d servers/python/.venv ] || python3 -m venv servers/python/.venv
  servers/python/.venv/bin/python -m pip install -q -r requirements.txt
fi
PY=servers/python/.venv/bin/python
node servers/node/servers.js > results/node-servers.log 2>&1 & NODE_PID=$!
$PY servers/python/servers.py > results/python-servers.log 2>&1 & PY_PID=$!
trap 'kill $NODE_PID $PY_PID 2>/dev/null' EXIT
for port in 4001 4002 4003 4004 4005 4006; do
  until curl -s -o /dev/null "http://127.0.0.1:$port/graphql"; do sleep 0.5; done
done
$PY probe/probe.py --json results/probe.json | tee results/probe.md
(cd servers/node && node audit.js) | tee results/graphql-http-audits.txt
(cd client && ../$PY -m pytest -q)
