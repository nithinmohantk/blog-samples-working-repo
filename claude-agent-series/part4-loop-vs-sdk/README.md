# Part 4: the hand-written loop and the Agent SDK, side by side

Sample code for the dataa.dev series on agentic integration with the Claude API, Part 4 (3 November 2026).

The same prescription assistant, built two ways, run through the same tasks:

| Folder | Implementation | Pinned version |
| :--- | :--- | :--- |
| `rxagent/` | Parts 1 and 3: a hand-written tool-use loop on the Messages API (server tools switched off for the benchmark) | `anthropic` 2.4.0 (API version 2026-10-21) |
| `rxagent_sdk/` | Part 2: the Claude Agent SDK with in-process MCP tools, `can_use_tool`, hooks and a locked-down configuration | `claude-agent-sdk` 0.2.176 (bundles Claude Code 2.1.316) |

`bench.py` runs five tasks through both, several times each, with a fresh synthetic back end per run and automatic approval policies:

| Task | Prompt | Approval policy | Pass when |
| :--- | :--- | :--- | :--- |
| `lookup` | Is RX-1002 still active, and has it been dispensed? | deny | Both lookups ran, the answer names RX-1002, nothing was cancelled |
| `patient` | What is patient P-001 currently prescribed? | deny | The patient's prescriptions were listed and both appear in the answer |
| `unknown` | What is the status of RX-9999? | deny | The answer names RX-9999 and nothing was cancelled |
| `cancel_denied` | Cancel RX-1003 (dry cough on ramipril) | deny | RX-1003 is still active and the cancellation was requested at most once |
| `cancel_approved` | The same | approve | RX-1003 is cancelled, by exactly one executed call |

The checks look at the record and the tool calls, not only at the wording of the answer.

## Run

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest -q                     # 31 offline tests, no API key needed
export ANTHROPIC_API_KEY=...                      # a workspace key with a spend limit
.venv/bin/python bench.py --reps 3                # 30 live runs; results.jsonl plus a summary table
```

A key that can act on more than one workspace also needs `ANTHROPIC_WORKSPACE_ID`. Cost is computed from usage at list prices for the loop and taken from `ResultMessage.total_cost_usd` for the SDK.

All data is synthetic. Do not point this sample at real patient records.
