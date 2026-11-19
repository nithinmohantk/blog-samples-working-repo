# A production agent harness, part by part

Sample code for the article "[What an Agent Harness Needs Before Production: Eleven Failures and the Part That Stops Each](https://www.dataa.dev/2026/09/15/agent-harness-production-eleven-failures/)".

An agent harness is the code around the model: the loop, the tools, and everything that decides what the
model's requests are allowed to do. This sample has two of them. `harness/bare.py` is the fourteen-line loop
most agents start as. `harness/loop.py` is the same loop with the parts a production system needs. A lab runs
eleven failures against both, each in its own process, and checks what happened.

The model is a scripted stand-in, so every run repeats exactly. No hosted model is called.

| Path | What it is |
| --- | --- |
| `harness/bare.py` | The bare loop |
| `harness/loop.py` | The loop, and the eight steps every tool call passes through |
| `harness/tools.py` | Tools with a JSON Schema contract, an effect (read or write), a time limit and a retry count |
| `harness/budget.py` | Limits on model calls, tool calls, time, result size and context size |
| `harness/policy.py` | Writes need an approver, and the default approver says no |
| `harness/store.py` | SQLite: the conversation after every step, and the result of every write by idempotency key |
| `harness/sandbox.py` | Generated code in a limited child process, or in a container with no network |
| `lab/` | Eleven scenarios, run on both loops, with 25 checks on the outcomes |
| `tests/` | 12 unit tests for the harness |

## Run it

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python -m unittest discover -s tests -t .
python -m lab.run out            # add --docker to also run generated code in a container
```

Linux only: the process sandbox uses `resource` limits and `preexec_fn`.

## What it uses

Python 3.13, `jsonschema`, the OpenTelemetry SDK, SQLite from the standard library, and Docker for the container
sandbox. Span names and attributes follow the OpenTelemetry GenAI semantic conventions (`invoke_agent`, `chat`,
`execute_tool`), which are marked as in development.

## Limits

- The process sandbox keeps the agent alive and keeps its environment out of generated code. It does not isolate the network or the file system. The lab shows that.
- A tool that times out is abandoned, not killed: its thread keeps running. Code that must be stopped belongs in the sandbox.
- Exactly-once across a crash needs the downstream system to honour the idempotency key. The lab's ledger does.
- One process, one SQLite file. No concurrency control between two workers resuming the same run.
- The approver is a function. A real one asks a person and records who answered.
- `FAKE_API_KEY` in the lab is a made-up value.
