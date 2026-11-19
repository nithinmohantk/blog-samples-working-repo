"""Claude Code's MCP allowlist and denylist rules, as documented.

Source: "Control MCP server access for your organization",
https://code.claude.com/docs/en/managed-mcp (read 19 Nov 2026).

This is a model of the documented behaviour for reviewing a policy before it
is deployed. Claude Code itself is the authority: confirm a deployed policy
with `claude mcp list` on a managed machine.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

Source = Literal["user", "project", "local", "plugin", "connector", "cli", "managed_file", "managed_settings", "builtin"]
_VAR = re.compile(r"\$\{[^}]+\}")


@dataclass(frozen=True)
class Server:
    name: str
    url: str | None = None                 # remote (http or sse) server
    command: tuple[str, ...] | None = None  # stdio server: command and arguments
    source: Source = "user"

    @property
    def remote(self) -> bool:
        return self.url is not None

    def uses_var_expansion(self) -> bool:
        parts = [self.url or "", *(self.command or ())]
        return any(_VAR.search(p) for p in parts)


@dataclass
class Policy:
    """The lists after merging every scope, plus the managed lock."""
    allowed: list[dict] | None = None       # None means unset: every server allowed
    denied: list[dict] = field(default_factory=list)
    managed_only: bool = False              # allowManagedMcpServersOnly
    managed_allowed: list[dict] | None = None

    @classmethod
    def from_scopes(cls, managed: dict, others: list[dict]) -> "Policy":
        """Merge settings documents the way the docs describe: denylists always
        merge; allowlists merge unless the managed source sets the lock."""
        lock = bool(managed.get("allowManagedMcpServersOnly"))
        denied = list(managed.get("deniedMcpServers", []))
        for doc in others:
            denied += doc.get("deniedMcpServers", [])
        sources = [managed] if lock else [managed, *others]
        allow_lists = [d["allowedMcpServers"] for d in sources if "allowedMcpServers" in d]
        allowed = None if not allow_lists else [e for lst in allow_lists for e in lst]
        return cls(allowed=allowed, denied=denied, managed_only=lock,
                   managed_allowed=managed.get("allowedMcpServers"))


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str


def url_matches(pattern: str, url: str) -> bool:
    """`*` matches anything, anywhere, including the scheme. Host matching is
    case-insensitive and ignores a trailing dot; paths are case-sensitive; a
    pattern with no path matches any path."""
    p_scheme, _, p_rest = pattern.partition("://")
    u_scheme, _, u_rest = url.partition("://")
    p_host, slash, p_path = p_rest.partition("/")
    u_host, _, u_path = u_rest.partition("/")
    if not slash:
        p_path = "*"
    norm = lambda h: h.lower().rstrip(".")
    return (_glob(p_scheme.lower(), u_scheme.lower())
            and _glob(norm(p_host), norm(u_host))
            and _glob(p_path, u_path))


def _glob(pattern: str, text: str) -> bool:
    rx = "".join(".*" if ch == "*" else re.escape(ch) for ch in pattern)
    return re.fullmatch(rx, text, flags=re.DOTALL) is not None


def _matches(entry: dict, s: Server) -> bool:
    if "serverUrl" in entry:
        return s.url is not None and url_matches(entry["serverUrl"], s.url)
    if "serverCommand" in entry:
        return s.command is not None and tuple(entry["serverCommand"]) == s.command
    if "serverName" in entry:
        return entry["serverName"] == s.name
    return False


def evaluate(policy: Policy, s: Server) -> Decision:
    for e in policy.denied:
        if _matches(e, s):
            return Decision(False, f"denylist: {e}")
    skips = s.source in ("managed_settings", "builtin") or (s.source == "managed_file" and not s.uses_var_expansion())
    if skips:
        return Decision(True, "organization or built-in server: allowlist not checked")
    allowed = policy.allowed
    if allowed is None:
        return Decision(True, "no allowlist set")
    key = "serverUrl" if s.remote else "serverCommand"
    typed = [e for e in allowed if key in e]
    if typed:
        hit = next((e for e in typed if _matches(e, s)), None)
        return Decision(hit is not None, f"allowlist {key}: {hit}" if hit else f"no {key} entry matches")
    named = [e for e in allowed if "serverName" in e]
    hit = next((e for e in named if _matches(e, s)), None)
    return Decision(hit is not None, f"allowlist serverName: {hit}" if hit else "not on the allowlist")
