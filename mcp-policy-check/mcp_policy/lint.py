"""Flags patterns in a managed MCP policy that look like controls but are not."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Finding:
    level: str  # "high", "medium", "info"
    code: str
    message: str


def lint(managed: dict) -> list[Finding]:
    out: list[Finding] = []
    allowed = managed.get("allowedMcpServers")
    denied = managed.get("deniedMcpServers", [])

    if allowed is None:
        out.append(Finding("high", "no_allowlist",
                           "No allowedMcpServers: every server a user adds can load unless it is denied."))
    else:
        if not managed.get("allowManagedMcpServersOnly"):
            out.append(Finding("high", "allowlist_not_locked",
                               "allowManagedMcpServersOnly is not true: user and project allowlists merge in and can widen this one."))
        if not allowed:
            out.append(Finding("info", "empty_allowlist", "Empty allowlist: no user-added servers can load."))
        names = [e["serverName"] for e in allowed if "serverName" in e]
        has_url = any("serverUrl" in e for e in allowed)
        has_cmd = any("serverCommand" in e for e in allowed)
        if names and not (has_url and has_cmd):
            out.append(Finding("high", "allow_by_name",
                               f"serverName entries {names} allow any server a user gives that name; "
                               "add serverUrl and serverCommand entries so names stop counting."))
        for e in allowed:
            url = e.get("serverUrl")
            if not url:
                continue
            scheme, _, rest = url.partition("://")
            host = rest.split("/", 1)[0]
            if scheme in ("http", "*") and not host.startswith(("localhost", "127.0.0.1")):
                out.append(Finding("medium", "plain_http",
                                   f"{url} allows unencrypted HTTP; MCP traffic can carry code and secrets."))
            bare = host.split(":", 1)[0]
            if bare == "*" or (bare.startswith("*") and "." not in bare[1:].lstrip(".")):
                out.append(Finding("high", "any_host", f"{url} matches any host, or a whole top-level domain."))
        for e in allowed:
            cmd = e.get("serverCommand")
            if cmd and any(a.endswith("@latest") for a in cmd):
                out.append(Finding("medium", "unpinned_package",
                                   f"{cmd} runs whatever version is latest at launch; pin a version."))

    for e in denied:
        if set(e) == {"serverName"}:
            out.append(Finding("info", "deny_by_name",
                               f"Denying {e['serverName']!r} by name blocks only servers with that label; "
                               "add the URL or command too."))
    return out
