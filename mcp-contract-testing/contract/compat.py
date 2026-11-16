"""Classify the differences between two MCP contract snapshots.

Every difference becomes a finding at one of three levels:

  breaking    a client written against the old contract can now fail, or be misled
  review      a machine cannot tell whether it is safe; a person has to read it
  compatible  old clients are unaffected

The rules follow from who has to tolerate whom. A tool's input schema describes what the server
accepts, so it may only get wider: anything the old schema allowed must still be allowed. An
output schema describes what the server produces, so it may only get narrower: anything the new
server returns must still fit what old consumers expected.

Pure functions, no MCP dependency: the input is two dictionaries produced by snapshot.py.
"""
from __future__ import annotations

import copy
import json
from dataclasses import asdict, dataclass
from typing import Any, Literal

Level = Literal["breaking", "review", "compatible"]
Direction = Literal["accepts", "produces"]
ORDER = {"breaking": 0, "review": 1, "compatible": 2}

LOWER_BOUNDS = ("minimum", "exclusiveMinimum", "minLength", "minItems", "minProperties")
UPPER_BOUNDS = ("maximum", "exclusiveMaximum", "maxLength", "maxItems", "maxProperties")
COSMETIC = ("title", "examples", "$comment")
HANDLED = {"type", "properties", "required", "additionalProperties", "enum", "const", "items", "anyOf", "oneOf",
           "pattern", "format", "default", "description", "$defs", "definitions", *LOWER_BOUNDS, *UPPER_BOUNDS, *COSMETIC}
WIDENINGS = {("integer", "number")}  # an integer is a number; nothing else converts safely


@dataclass(frozen=True)
class Finding:
    level: Level
    where: str
    rule: str
    detail: str


def resolve(schema: Any, root: dict[str, Any] | None = None, depth: int = 0) -> Any:
    """Inline local $ref pointers so that two schemas can be compared structurally."""
    root = schema if root is None else root
    if depth > 40:
        return {"$comment": "recursive reference not expanded"}
    if isinstance(schema, list):
        return [resolve(item, root, depth) for item in schema]
    if not isinstance(schema, dict):
        return schema
    if "$ref" in schema and isinstance(schema["$ref"], str) and schema["$ref"].startswith("#/"):
        target: Any = root
        for part in schema["$ref"][2:].split("/"):
            target = target[part.replace("~1", "/").replace("~0", "~")]
        merged = {**copy.deepcopy(target), **{k: v for k, v in schema.items() if k != "$ref"}}
        return resolve(merged, root, depth + 1)
    return {key: resolve(value, root, depth) for key, value in schema.items() if key not in ("$defs", "definitions")}


def types_of(schema: dict[str, Any]) -> set[str]:
    declared = schema.get("type")
    if declared is None:
        return set()
    return set(declared) if isinstance(declared, list) else {declared}


def branches(schema: dict[str, Any]) -> list[dict[str, Any]] | None:
    return schema.get("anyOf") or schema.get("oneOf")


def branch_key(schema: dict[str, Any]) -> str:
    return "|".join(sorted(types_of(schema))) or json.dumps(schema, sort_keys=True)[:60]


class SchemaDiff:
    """Compare two JSON Schemas in one direction and collect findings."""

    def __init__(self, direction: Direction) -> None:
        self.direction = direction
        self.findings: list[Finding] = []

    def add(self, level: Level, where: str, rule: str, detail: str) -> None:
        self.findings.append(Finding(level, where, rule, detail))

    def narrowed(self, where: str, rule: str, detail: str) -> None:
        """The new schema allows less than the old one."""
        self.add("breaking" if self.direction == "accepts" else "compatible", where, rule, detail)

    def widened(self, where: str, rule: str, detail: str) -> None:
        """The new schema allows more than the old one."""
        self.add("compatible" if self.direction == "accepts" else "breaking", where, rule, detail)

    def compare(self, old: dict[str, Any], new: dict[str, Any], where: str) -> None:
        old_branches, new_branches = branches(old), branches(new)
        if old_branches or new_branches:
            self.compare_branches(old_branches or [old], new_branches or [new], where)
            return
        self.compare_types(old, new, where)
        self.compare_enum(old, new, where)
        self.compare_bounds(old, new, where)
        self.compare_text(old, new, where)
        if "object" in types_of(old) | types_of(new) or "properties" in old or "properties" in new:
            self.compare_object(old, new, where)
        if isinstance(old.get("items"), dict) and isinstance(new.get("items"), dict):
            self.compare(old["items"], new["items"], f"{where}[]")
        for key in sorted((set(old) | set(new)) - HANDLED):
            if old.get(key) != new.get(key):
                self.add("review", where, "unclassified-keyword", f"{key}: {json.dumps(old.get(key))} -> {json.dumps(new.get(key))}")

    def compare_branches(self, old: list[dict[str, Any]], new: list[dict[str, Any]], where: str) -> None:
        before, after = {branch_key(b): b for b in old}, {branch_key(b): b for b in new}
        for key in sorted(before.keys() - after.keys()):
            self.narrowed(where, "alternative-removed", f"no longer allows {key}")
        for key in sorted(after.keys() - before.keys()):
            self.widened(where, "alternative-added", f"now also allows {key}")
        for key in sorted(before.keys() & after.keys()):
            self.compare(before[key], after[key], where)

    def compare_types(self, old: dict[str, Any], new: dict[str, Any], where: str) -> None:
        before, after = types_of(old), types_of(new)
        if before == after or not before or not after:
            if before != after:
                self.add("review", where, "type-declaration-changed", f"{sorted(before) or 'any'} -> {sorted(after) or 'any'}")
            return
        if before < after or all((b, a) in WIDENINGS for b in before for a in after):
            self.widened(where, "type-widened", f"{sorted(before)} -> {sorted(after)}")
        elif after < before or all((a, b) in WIDENINGS for b in before for a in after):
            self.narrowed(where, "type-narrowed", f"{sorted(before)} -> {sorted(after)}")
        else:
            self.add("breaking", where, "type-changed", f"{sorted(before)} -> {sorted(after)}")

    def compare_enum(self, old: dict[str, Any], new: dict[str, Any], where: str) -> None:
        def allowed(schema: dict[str, Any]) -> list[Any] | None:
            if "const" in schema:
                return [schema["const"]]
            return schema.get("enum")

        before, after = allowed(old), allowed(new)
        if before is None and after is None:
            return
        if before is None:
            self.narrowed(where, "enum-introduced", f"now limited to {json.dumps(after)}")
        elif after is None:
            self.widened(where, "enum-dropped", f"was limited to {json.dumps(before)}")
        else:
            gone = [v for v in before if v not in after]
            came = [v for v in after if v not in before]
            if gone:
                self.narrowed(where, "enum-value-removed", json.dumps(gone))
            if came:
                self.widened(where, "enum-value-added", json.dumps(came))

    def compare_bounds(self, old: dict[str, Any], new: dict[str, Any], where: str) -> None:
        for keys, tighter in ((LOWER_BOUNDS, lambda b, a: a > b), (UPPER_BOUNDS, lambda b, a: a < b)):
            for key in keys:
                before, after = old.get(key), new.get(key)
                if before == after:
                    continue
                change = f"{key}: {before} -> {after}"
                if before is None:
                    self.narrowed(where, "constraint-added", change)
                elif after is None:
                    self.widened(where, "constraint-removed", change)
                elif tighter(before, after):
                    self.narrowed(where, "constraint-tightened", change)
                else:
                    self.widened(where, "constraint-loosened", change)
        for key in ("pattern", "format"):
            before, after = old.get(key), new.get(key)
            if before == after:
                continue
            if before is None:
                self.narrowed(where, f"{key}-added", str(after))
            elif after is None:
                self.widened(where, f"{key}-removed", str(before))
            else:  # whether one regular expression contains another is not something to guess
                self.add("review", where, f"{key}-changed", f"{before} -> {after}")

    def compare_text(self, old: dict[str, Any], new: dict[str, Any], where: str) -> None:
        if old.get("description") != new.get("description"):
            self.add("review", where, "description-changed", f"{old.get('description')!r} -> {new.get('description')!r}")
        if "default" in old or "default" in new:
            if old.get("default", ...) != new.get("default", ...):
                self.add("review", where, "default-changed",
                         f"{json.dumps(old.get('default')) if 'default' in old else 'none'} -> {json.dumps(new.get('default')) if 'default' in new else 'none'}")

    def compare_object(self, old: dict[str, Any], new: dict[str, Any], where: str) -> None:
        before, after = old.get("properties", {}), new.get("properties", {})
        required_before, required_after = set(old.get("required", [])), set(new.get("required", []))
        for name in sorted(before.keys() - after.keys()):
            if self.direction == "accepts":
                self.add("breaking", f"{where}.{name}", "parameter-removed", "callers that send it are rejected or silently ignored")
            else:
                self.add("breaking", f"{where}.{name}", "field-removed", "consumers that read it get nothing")
        for name in sorted(after.keys() - before.keys()):
            if self.direction == "accepts":
                if name in required_after:
                    self.add("breaking", f"{where}.{name}", "required-parameter-added", "existing callers do not send it")
                else:
                    self.add("compatible", f"{where}.{name}", "optional-parameter-added", "existing callers are unaffected")
            elif old.get("additionalProperties") is False:
                self.add("breaking", f"{where}.{name}", "field-added-to-closed-object", "the old schema forbade extra fields")
            else:
                self.add("compatible", f"{where}.{name}", "field-added", "consumers that ignore unknown fields are unaffected")
        for name in sorted(before.keys() & after.keys()):
            path = f"{where}.{name}"
            if name in required_after and name not in required_before:
                self.narrowed(path, "became-required", "optional -> required")
            elif name in required_before and name not in required_after:
                self.widened(path, "became-optional", "required -> optional")
            self.compare(before[name], after[name], path)
        closed_before, closed_after = old.get("additionalProperties") is False, new.get("additionalProperties") is False
        if closed_after and not closed_before:
            self.narrowed(where, "object-closed", "additionalProperties is now false")
        elif closed_before and not closed_after:
            self.widened(where, "object-opened", "additionalProperties is no longer false")


def schema_findings(old: dict[str, Any] | None, new: dict[str, Any] | None, where: str, direction: Direction) -> list[Finding]:
    if old is None and new is None:
        return []
    if old is None:
        return [Finding("compatible", where, "schema-added", "there was none before")]
    if new is None:
        level: Level = "breaking" if direction == "produces" else "review"
        return [Finding(level, where, "schema-removed", "consumers can no longer validate against it")]
    diff = SchemaDiff(direction)
    diff.compare(resolve(old), resolve(new), where)
    return diff.findings


def by_key(entries: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    return {entry[key]: entry for entry in entries}


def tool_findings(old: dict[str, Any], new: dict[str, Any]) -> list[Finding]:
    name, found = old["name"], []
    if old.get("description") != new.get("description"):
        found.append(Finding("review", f"tools.{name}", "tool-description-changed",
                             f"{old.get('description')!r} -> {new.get('description')!r}"))
    if old.get("title") != new.get("title"):
        found.append(Finding("compatible", f"tools.{name}", "tool-title-changed", f"{old.get('title')!r} -> {new.get('title')!r}"))
    before, after = old.get("annotations", {}), new.get("annotations", {})
    for hint in sorted(set(before) | set(after)):
        if before.get(hint) == after.get(hint):
            continue
        change = f"{hint}: {json.dumps(before.get(hint))} -> {json.dumps(after.get(hint))}"
        if hint == "readOnlyHint" and before.get(hint) is True:
            found.append(Finding("breaking", f"tools.{name}", "no-longer-read-only", change + "; clients that skip approval for read-only tools will not ask"))
        else:
            found.append(Finding("review", f"tools.{name}", "annotation-changed", change))
    found += schema_findings(old.get("inputSchema"), new.get("inputSchema"), f"tools.{name}.input", "accepts")
    found += schema_findings(old.get("outputSchema"), new.get("outputSchema"), f"tools.{name}.output", "produces")
    return found


def compare(old: dict[str, Any], new: dict[str, Any]) -> list[Finding]:
    found: list[Finding] = []
    if old["server"].get("name") != new["server"].get("name"):
        found.append(Finding("review", "server.name", "server-renamed", f"{old['server'].get('name')} -> {new['server'].get('name')}"))
    if old.get("protocolVersion") != new.get("protocolVersion"):
        found.append(Finding("review", "protocolVersion", "protocol-version-changed", f"{old.get('protocolVersion')} -> {new.get('protocolVersion')}"))
    if old.get("instructions") != new.get("instructions"):
        found.append(Finding("review", "instructions", "instructions-changed", f"{old.get('instructions')!r} -> {new.get('instructions')!r}"))

    def flatten(capabilities: dict[str, Any], prefix: str = "") -> dict[str, Any]:
        flat: dict[str, Any] = {}
        for key, value in capabilities.items():
            flat[prefix + key] = True
            if isinstance(value, dict):
                flat.update(flatten(value, f"{prefix}{key}."))
            elif isinstance(value, bool):
                flat[prefix + key] = value
        return flat

    before, after = flatten(old.get("capabilities", {})), flatten(new.get("capabilities", {}))
    for key in sorted(set(before) | set(after)):
        if before.get(key, False) and not after.get(key, False):
            found.append(Finding("breaking", f"capabilities.{key}", "capability-removed", "clients that relied on it stop working"))
        elif after.get(key, False) and not before.get(key, False):
            found.append(Finding("compatible", f"capabilities.{key}", "capability-added", "new for clients that look for it"))

    old_tools, new_tools = by_key(old.get("tools", []), "name"), by_key(new.get("tools", []), "name")
    for name in sorted(old_tools.keys() - new_tools.keys()):
        found.append(Finding("breaking", f"tools.{name}", "tool-removed", "calls return an unknown-tool error; a rename looks the same"))
    for name in sorted(new_tools.keys() - old_tools.keys()):
        hints = new_tools[name].get("annotations", {})
        level: Level = "compatible" if hints.get("readOnlyHint") is True else "review"
        found.append(Finding(level, f"tools.{name}", "tool-added",
                             "read-only" if level == "compatible" else "a new tool that can change state widens what every connected agent may do"))
    for name in sorted(old_tools.keys() & new_tools.keys()):
        found += tool_findings(old_tools[name], new_tools[name])

    for section, key in (("resources", "uri"), ("resourceTemplates", "uriTemplate"), ("prompts", "name")):
        before_set, after_set = by_key(old.get(section, []), key), by_key(new.get(section, []), key)
        for name in sorted(before_set.keys() - after_set.keys()):
            found.append(Finding("breaking", f"{section}.{name}", "entry-removed", "clients that read it get an error"))
        for name in sorted(after_set.keys() - before_set.keys()):
            found.append(Finding("compatible", f"{section}.{name}", "entry-added", "new"))
        for name in sorted(before_set.keys() & after_set.keys()):
            was, now = before_set[name], after_set[name]
            if was.get("description") != now.get("description"):
                found.append(Finding("review", f"{section}.{name}", "description-changed", f"{was.get('description')!r} -> {now.get('description')!r}"))
            if was.get("mimeType") != now.get("mimeType"):
                level = "compatible" if was.get("mimeType") is None else "breaking"
                found.append(Finding(level, f"{section}.{name}", "mime-type-declared" if level == "compatible" else "mime-type-changed",
                                     f"{was.get('mimeType')} -> {now.get('mimeType')}"))
            if section == "prompts":
                old_args, new_args = by_key(was.get("arguments", []), "name"), by_key(now.get("arguments", []), "name")
                for argument in sorted(old_args.keys() - new_args.keys()):
                    found.append(Finding("breaking", f"prompts.{name}.{argument}", "prompt-argument-removed", "callers that send it are rejected"))
                for argument in sorted(new_args.keys() - old_args.keys()):
                    needed = new_args[argument].get("required", False)
                    found.append(Finding("breaking" if needed else "compatible", f"prompts.{name}.{argument}",
                                         "required-prompt-argument-added" if needed else "optional-prompt-argument-added", ""))
                for argument in sorted(old_args.keys() & new_args.keys()):
                    if new_args[argument].get("required", False) and not old_args[argument].get("required", False):
                        found.append(Finding("breaking", f"prompts.{name}.{argument}", "prompt-argument-became-required", ""))
    return sorted(found, key=lambda f: (ORDER[f.level], f.where, f.rule))


def worst(findings: list[Finding]) -> Level | None:
    return min((f.level for f in findings), key=ORDER.__getitem__, default=None)


def as_dicts(findings: list[Finding]) -> list[dict[str, str]]:
    return [asdict(f) for f in findings]
