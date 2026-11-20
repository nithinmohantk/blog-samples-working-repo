# Part 1: a hand-written tool-use loop on the Claude Messages API

Sample code for [Agentic Integration with the Claude API, Part 1: Writing the Tool-Use Loop Yourself](https://www.dataa.dev/2026/10/13/claude-api-agentic-integration-part-1-tool-use-loop/) (dataa.dev, 13 October 2026).

A prescription status assistant over a synthetic e-prescription service. Claude Opus 5.5 decides which lookups to make; the loop decides what is allowed to happen.

| File | What it does |
| :--- | :--- |
| `rxagent/rx_service.py` | Synthetic e-prescription back end (invented data): lookups and a cancel operation with business rules |
| `rxagent/tools.py` | Four tools with strict JSON Schemas; one changes state |
| `rxagent/loop.py` | The loop: stop reasons, parallel read-only calls, an approval gate for writes, instructive `is_error` results, turn and tool budgets, retry of a cut-off tool call, prompt caching, usage and cost per task, JSON audit events |
| `rxagent/__main__.py` | Command line: prints each turn's stop reason, tokens, cache use, tool calls and request ID |
| `runner_version.py` | The same lookups with the SDK's tool runner (beta), for comparison |
| `tests/` | 11 offline tests: a scripted fake for the loop, and the real SDK client against a mock HTTP transport |

## Run

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest -q                       # offline, no API key needed
export ANTHROPIC_API_KEY=...                        # from a workspace with a spend limit
.venv/bin/python -m rxagent "What is the status of RX-1002, and has it been dispensed?"
.venv/bin/python -m rxagent --approve ask "Cancel RX-1003: the patient developed a dry cough on ramipril."
```

Versions are pinned to what was current on 13 October 2026: `anthropic==1.13.0`, which sends API version `2023-06-01`.
