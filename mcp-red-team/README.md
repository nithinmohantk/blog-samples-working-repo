# Red-teaming your own MCP server

Sample for the dataa.dev article "[Red-Teaming an MCP Server: Poisoned Descriptions, Rug Pulls and Confused Deputies](https://www.dataa.dev/2026/02/17/red-teaming-an-mcp-server/)".

Two questions, tested separately. What does a client do when a server is hostile? And what does a server
do when its arguments are hostile? Nothing here calls a model or a cloud service.

| Path | What it is |
| --- | --- |
| `attacks/hostile_server.py` | An MCP server with fifteen modes, each misbehaving in one way. Never connect a real agent to it |
| `guard/scan.py` | Pattern checks on tool descriptions, schemas, server instructions and results |
| `guard/pins.py` | Fingerprints of approved tool definitions, and verification against them |
| `guard/session.py` | `GuardedSession`: limits, pins and result checks around `mcp.ClientSession` |
| `corpus/descriptions.json` | Forty hand-written tool definitions, twenty hostile and twenty benign |
| `deputy/server.py` | Four tools written twice, naive and hardened: files, outbound requests, tenant data, SQL |
| `lab/run.py` | Runs every scenario against a plain client and a guarded one, and every attack against both tool versions |
| `tests/run.py` | 25 unit tests for the scanner and the pin store |

## Run

    ./ci.sh out      # Python 3.13; installs into a temporary virtual environment with uv

## What was verified

GitHub Actions, `ubuntu-latest`, Python 3.13: MCP Python SDK 1.26.0, protocol revision 2025-11-25,
dependencies resolved as of 16 February 2026. Transcripts and JSON for the latest run are on the
`ci-results-mcp-red-team` branch.

## What this does not show

- No model is involved. The lab shows that hostile text reaches the application unchanged and whether the
  guard notices it. It does not measure whether a given model would obey that text.
- The guard was written against these fifteen scenarios, so stopping all fifteen proves little. The corpus
  is the fairer test, and there the scanner misses every paraphrase.
- The corpus and the rules were written by the same hand. Its numbers show the kinds of miss and false
  alarm, not a rate to quote.
- One client library, in Python. Desktop and IDE clients were not tested.
- The hardened outbound tool uses an exact-origin allow-list and refuses redirects. It does not defend
  against DNS rebinding; production code should also check the resolved address.
- The pin file is only as good as the review at approval time.
