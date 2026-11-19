import json

from mcp_policy.__main__ import main
from mcp_policy.lint import lint


def codes(managed):
    return {f.code for f in lint(managed)}


def test_good_policy_has_no_high_findings():
    good = {"allowManagedMcpServersOnly": True,
            "allowedMcpServers": [{"serverUrl": "https://api.githubcopilot.com/*"},
                                  {"serverCommand": ["npx", "-y", "@modelcontextprotocol/server-filesystem@2026.1.14", "."]}],
            "deniedMcpServers": [{"serverUrl": "https://*.untrusted.example.com/*"}]}
    assert not [f for f in lint(good) if f.level == "high"]


def test_weak_patterns_are_flagged():
    assert "no_allowlist" in codes({})
    assert "allowlist_not_locked" in codes({"allowedMcpServers": [{"serverUrl": "https://a.example/*"}]})
    assert "allow_by_name" in codes({"allowManagedMcpServersOnly": True, "allowedMcpServers": [{"serverName": "github"}]})
    assert "plain_http" in codes({"allowedMcpServers": [{"serverUrl": "http://mcp.example.com/*"}]})
    assert "plain_http" not in codes({"allowedMcpServers": [{"serverUrl": "http://localhost:*/*"}]})
    assert "any_host" in codes({"allowedMcpServers": [{"serverUrl": "https://*/*"}]})
    assert "any_host" in codes({"allowedMcpServers": [{"serverUrl": "https://*.com/*"}]})
    assert "any_host" not in codes({"allowedMcpServers": [{"serverUrl": "https://*.example.com/*"}]})
    assert "unpinned_package" in codes({"allowedMcpServers": [{"serverCommand": ["npx", "@playwright/mcp@latest"]}]})
    assert "deny_by_name" in codes({"deniedMcpServers": [{"serverName": "dangerous-server"}]})
    assert "empty_allowlist" in codes({"allowManagedMcpServersOnly": True, "allowedMcpServers": []})


def test_cli_reports_and_sets_exit_code(tmp_path, capsys):
    policy = tmp_path / "managed-settings.json"
    policy.write_text(json.dumps({
        "allowManagedMcpServersOnly": True,
        "allowedMcpServers": [{"serverUrl": "https://api.githubcopilot.com/*"},
                              {"serverCommand": ["npx", "-y", "@acme/mcp-jira@3.2.1"]}],
        "deniedMcpServers": [{"serverName": "pastebin"}]}))
    inventory = tmp_path / "inventory.json"
    inventory.write_text(json.dumps([
        {"name": "github", "url": "https://api.githubcopilot.com/mcp/"},
        {"name": "jira", "command": ["npx", "-y", "@acme/mcp-jira@3.2.1"]},
        {"name": "github", "command": ["node", "/tmp/github-mcp.js"]},
        {"name": "scratch", "url": "https://mcp.scratchpad.example/mcp"},
    ]))
    assert main([str(policy), str(inventory)]) == 0
    out = capsys.readouterr().out
    assert "deny_by_name" in out
    lines = [l for l in out.splitlines() if l.startswith(("LOAD", "BLOCK"))]
    assert [l.split()[0] for l in lines] == ["LOAD", "LOAD", "BLOCK", "BLOCK"]
