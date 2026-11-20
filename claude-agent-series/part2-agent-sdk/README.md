# Part 2: the same agent on the Claude Agent SDK

Sample code for the dataa.dev series on agentic integration with the Claude API, Part 2 (20 October 2026).

The Part 1 prescription assistant rebuilt on `claude-agent-sdk` 0.2.168 (bundles Claude Code 2.1.301). The SDK runs the agent loop in a Claude Code process; the tools run in this Python process through an in-process MCP server.

| File | What it does |
| :--- | :--- |
| `rxagent_sdk/rx_service.py` | The same synthetic e-prescription back end as Part 1 |
| `rxagent_sdk/agent.py` | Tools (`@tool` with annotations), the approval gate (`can_use_tool`), audit hooks (`PreToolUse`, `PostToolUse`) and the locked-down `ClaudeAgentOptions` |
| `rxagent_sdk/__main__.py` | Command line: prints the session's tools, each tool call, turns, cost, tokens, audit events and the answer |
| `tests/` | 8 offline tests of the handlers, gate, hooks and options |

## Run

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest -q                       # offline, no API key needed
export ANTHROPIC_API_KEY=...                        # a workspace key with a spend limit
.venv/bin/python -m rxagent_sdk "What is the status of RX-1002, and has it been dispensed?"
.venv/bin/python -m rxagent_sdk --approve ask "Cancel RX-1003: the patient developed a dry cough on ramipril."
.venv/bin/python -m rxagent_sdk --no-tool-search "What is the status of RX-1002, and has it been dispensed?"
```

A key that can act on more than one workspace also needs `ANTHROPIC_WORKSPACE_ID`; the sample passes it to Claude Code as `ANTHROPIC_CUSTOM_HEADERS`.
