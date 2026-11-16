# Contract-testing an MCP server in CI

Sample for the dataa.dev article "Contract-Testing an MCP Server in CI: Snapshots, Breaking Changes and a Gate".

An MCP server's tool listing is its public contract: agents read it at run time and nothing compiles
against it. This folder takes a snapshot of that listing, classifies the difference between two snapshots
as breaking, review or compatible, and fails a build on a breaking change that has no major version bump.

Nothing here calls a model or a cloud service. Every server is a local process. The data is synthetic.

| Path | What it is |
| --- | --- |
| `server/app.py` | Stockroom, the server under test: five tools, one resource, one resource template, one prompt |
| `contract/snapshot.py` | Connects over stdio or Streamable HTTP and writes the canonical contract file |
| `contract/mcp-contract.json` | The committed contract of stockroom 1.4.0 |
| `contract/compat.py` | The compatibility rules, as pure functions over two snapshots |
| `contract/gate.py` | The build gate: exit 0 pass, 1 breaking without a major bump, 2 stale snapshot, 3 unreadable |
| `contract/calls.json`, `contract/replay.py` | Nine recorded calls, replayed and validated against the committed output schemas |
| `tests/run.py` | 45 unit tests for the rules |
| `lab/variants.py`, `lab/run_variants.py` | Twenty-one one-line changes to the server, and what the gate and the replay make of each |
| `lab/sdk_drift.py` | The same server file under SDK 1.9.4, 1.26.0, 1.30.0 and 2.3.0 |
| `ci.sh` | Runs all of the above and writes the transcripts |

## Run

    ./ci.sh out      # Python 3.13; installs into temporary virtual environments with uv

Use it on your own server:

    python contract/snapshot.py --stdio "python path/to/your_server.py" --out contract/mcp-contract.json
    python contract/gate.py --base base.json --head contract/mcp-contract.json --live live.json

The `contract-gate` job in `.github/workflows/mcp-contract.yml` is the same thing as a pipeline step.

## What was verified

GitHub Actions, `ubuntu-latest`, Python 3.13: MCP Python SDK 2.3.0, pydantic 2.14.2, jsonschema 4.26.0,
dependencies resolved as of 4 November 2026. Transcripts and JSON for the latest run are on the
`ci-results-mcp-contract` branch.

## What this does not show

- No model is involved. Whether a reworded description changes what an agent does is exactly what a schema
  comparison cannot tell you, which is why such changes are routed to a person.
- One SDK, in Python. Other SDKs generate schemas differently; the snapshot and the rules do not depend on
  the SDK, the observations about silent behaviour do.
- The rules cover the JSON Schema keywords that typed tool signatures produce. Anything else is reported
  for review, not guessed at.
- No authentication. Snapshot a protected server from inside the pipeline with whatever credential the
  pipeline already holds.
