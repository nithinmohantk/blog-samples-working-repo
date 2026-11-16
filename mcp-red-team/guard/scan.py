"""Static checks on what an MCP server says about itself, run before any of it reaches a model.

These are pattern checks. They catch the published tool-poisoning techniques and careless servers;
they do not catch a well-written paraphrase, and the lab measures how often they miss. Treat a clean
scan as "nothing obvious", never as "safe".
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Iterable

MAX_DESCRIPTION = 1000  # characters; longer descriptions are legitimate but rare, and worth a look


@dataclass(frozen=True)
class Finding:
    rule: str
    where: str
    evidence: str


def invisible(text: str) -> list[str]:
    """Characters that carry text a person cannot see: format controls, tag characters, bidi overrides."""
    found = []
    for ch in text:
        code = ord(ch)
        if 0xE0000 <= code <= 0xE007F or unicodedata.category(ch) == "Cf" or code in (0x2028, 0x2029):
            found.append(f"U+{code:04X}")
    return found


ADDRESSES_MODEL = re.compile(
    r"<\s*/?\s*(important|system|instructions?|secret|admin)\s*>"
    r"|\b(ignore|disregard|forget|override)\b.{0,40}\b(instruction|prompt|rule|guideline)s?\b"
    r"|\bdo not\b.{0,30}\b(tell|mention|inform|show|reveal|notify)\b.{0,30}\b(user|human|anyone)\b"
    r"|\b(without|never)\b.{0,20}\b(telling|asking|informing|notifying|ask|tell)\b.{0,20}\b(user|human)\b"
    r"|\b(system|assistant)\s+(note|message|prompt|override)\b"
    r"|\bbefore (using|calling|you use|you call)\b.{0,60}\b(read|fetch|open|load|send|include|call)\b"
    r"|\byou (must|should) (always|first|also)\b|\balways (call|add|include|send|use)\b",
    re.IGNORECASE | re.DOTALL)
SECRETS = re.compile(r"~/\.|\.ssh\b|id_rsa|\.env\b|\.aws\b|mcp\.json|\b(api[ _-]?key|credential|password|passphrase|private key|access token|secret)s?\b", re.IGNORECASE)
OTHER_TOOLS = re.compile(r"\b(other|another|any|different)\s+(tool|server|mcp)s?\b|\bfrom (the|any|another) .{0,20}server\b", re.IGNORECASE)
CONTACT = re.compile(r"https?://[^\s\"'<>]+|\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
CARRIER_NAMES = re.compile(r"^(side_?note|notes?|context|conversation|history|chat_?history|metadata|debug|extra|feedback|reasoning|scratchpad)$", re.IGNORECASE)
CARRIER_TEXT = re.compile(r"\b(conversation|chat history|everything|full (text|content|context)|contents? of|previous messages|system prompt)\b", re.IGNORECASE)
STATE_CHANGING = re.compile(r"\b(delete|remove|drop|erase|wipe|purge|send|write|update|create|transfer|pay|refund|cancel|execute|run|deploy|revoke|grant)", re.IGNORECASE)
PADDING = re.compile(r"[ \t ]{40,}|\n{8,}")


def scan_text(text: str, where: str, own_name: str = "", known_tools: Iterable[str] = ()) -> list[Finding]:
    found: list[Finding] = []
    hidden = invisible(text)
    if hidden:
        found.append(Finding("invisible-characters", where, f"{len(hidden)} hidden, first {hidden[0]}"))
        text = "".join(chr(ord(c) - 0xE0000) if 0xE0020 <= ord(c) <= 0xE007E else c for c in text)  # read what was hidden
    for rule, pattern in (("addresses-the-model", ADDRESSES_MODEL), ("mentions-secrets", SECRETS),
                          ("refers-to-other-tools", OTHER_TOOLS), ("padding", PADDING)):
        match = pattern.search(text)
        if match:
            found.append(Finding(rule, where, " ".join(match.group(0).split())[:60]))
    for other in known_tools:
        if other != own_name and re.search(rf"\b{re.escape(other)}\b", text):
            found.append(Finding("names-another-tool", where, other))
            break
    if len(text) > MAX_DESCRIPTION:
        found.append(Finding("oversized-text", where, f"{len(text)} characters"))
    return found


def walk_schema(schema: Any, where: str) -> Iterable[tuple[str, str]]:
    """Every string in a JSON Schema that a model will read: descriptions, titles, enums, defaults, examples."""
    if isinstance(schema, dict):
        for key, value in schema.items():
            path = f"{where}.{key}"
            if key in ("description", "title", "default", "const") and isinstance(value, str):
                yield path, value
            elif key in ("enum", "examples") and isinstance(value, list):
                for item in value:
                    if isinstance(item, str):
                        yield path, item
            else:
                yield from walk_schema(value, path)
    elif isinstance(schema, list):
        for index, item in enumerate(schema):
            yield from walk_schema(item, f"{where}[{index}]")


def scan_tool(tool: dict[str, Any], known_tools: Iterable[str] = ()) -> list[Finding]:
    name = tool["name"]
    description = tool.get("description") or ""
    found = scan_text(description, f"{name}.description", name, known_tools)
    contact = CONTACT.search(description)
    if contact:
        found.append(Finding("contact-in-description", f"{name}.description", contact.group(0)[:60]))
    schema = tool.get("inputSchema") or {}
    for where, text in walk_schema(schema, f"{name}.inputSchema"):
        found += scan_text(text, where, name, known_tools)
    for parameter, definition in (schema.get("properties") or {}).items():
        text = definition.get("description", "") if isinstance(definition, dict) else ""
        if CARRIER_NAMES.match(parameter) and (parameter in schema.get("required", []) or CARRIER_TEXT.search(text)):
            found.append(Finding("carrier-parameter", f"{name}.inputSchema.properties.{parameter}", "free-text parameter that invites context"))
        elif CARRIER_TEXT.search(text) and SECRETS.search(text):
            found.append(Finding("carrier-parameter", f"{name}.inputSchema.properties.{parameter}", "asks for context and secrets"))
    hints = tool.get("annotations") or {}
    if hints.get("readOnlyHint") is True and STATE_CHANGING.search(name.replace("_", " ") + " " + description):
        found.append(Finding("read-only-contradiction", f"{name}.annotations", "readOnlyHint is true, but the name or description changes state"))
    return found


def scan_listing(tools: list[dict[str, Any]], instructions: str | None = None, other_servers_tools: Iterable[str] = ()) -> list[Finding]:
    """Scan one server's listing. other_servers_tools are the tool names the user already has from other servers."""
    others = set(other_servers_tools)
    names = {tool["name"] for tool in tools} | others
    found = scan_text(instructions or "", "server.instructions", "", names)
    for tool in tools:
        if tool["name"] in others:
            found.append(Finding("name-collision", f"{tool['name']}", "another connected server already has a tool with this name"))
        found += scan_tool(tool, names)
    return found


def scan_result(text: str, known_tools: Iterable[str] = ()) -> list[Finding]:
    """A tool result is data. Text in it that addresses the model is the mark of an indirect injection."""
    return [f for f in scan_text(text[:20000], "result", "", known_tools) if f.rule in ("invisible-characters", "addresses-the-model", "names-another-tool")]
