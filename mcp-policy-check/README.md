# mcp-policy-check

Sample code for the dataa.dev article *Governing Claude Code and GitHub Copilot CLI in the Enterprise: Agent Policy, Defender, Entra Agent ID and the MCP Firewall* (19 Nov 2026).

A reviewer for Claude Code's managed MCP policy (`allowedMcpServers`, `deniedMcpServers`, `allowManagedMcpServersOnly`) to run in a pull request before the policy is deployed.

| File | What it does |
| :--- | :--- |
| `mcp_policy/model.py` | The documented evaluation: merge lists, denylist first, allowlist by `serverUrl` for remote servers and exact `serverCommand` for stdio servers, `serverName` only when no typed entries exist, organization and built-in servers skip the allowlist, URL wildcards |
| `mcp_policy/lint.py` | Flags policies that look like controls but are not: no allowlist, allowlist not locked to managed settings, allow by name, plain HTTP, any-host wildcards, unpinned `@latest` packages, deny by name only |
| `mcp_policy/__main__.py` | CLI: lint a policy and, given an inventory of servers (for example from Defender's MCP discovery), show which load. Exit code 2 on a high finding |
| `examples/` | A good policy, a weak policy, an inventory, and the CLI output printed in the article |

## Run

```bash
python3.12 -m venv .venv && .venv/bin/pip install pytest==8.3.3
.venv/bin/python -m pytest -q
.venv/bin/python -m mcp_policy examples/managed-settings.json examples/inventory.json
```

Standard library only at run time.

## What was verified

19 tests pass with Python 3.12 and pytest 8.3.3. The tests in `tests/test_documented_examples.py` are the worked examples from Claude Code's documentation, "Control MCP server access for your organization" (code.claude.com/docs/en/managed-mcp, read 19 Nov 2026): the URL-only, command-only, mixed, name-only and denylist-override tables, exact command matching, URL wildcard rules, organization servers and `${VAR}` expansion, the managed lock, and unset versus empty allowlists.

This is a model of the documented behaviour, not Claude Code itself. Running the Claude Code CLI against the policies was not possible in the environment used to write the article. Confirm a deployed policy on a managed machine with `claude mcp list` and `claude mcp add --transport http test https://example.com/mcp`. GitHub Copilot's enterprise `managed-settings.json` uses the same `allowedMcpServers` / `serverUrl` / `serverCommand` shapes, but its matching rules were not checked against this model.
