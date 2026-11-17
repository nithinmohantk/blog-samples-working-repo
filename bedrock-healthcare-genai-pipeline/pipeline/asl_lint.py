"""Structural checks on the state machine that do not need AWS.

Catches the faults that otherwise appear only at deploy time or, worse, on the
one path nobody exercised: a Next that names no state, a state nothing reaches,
a Choice with no Default, a gate that can reach production without passing
through the evaluation and sign-off states.
"""

from __future__ import annotations

import json
from pathlib import Path


def _targets(state: dict) -> list[str]:
    out = []
    for key in ("Next", "Default"):
        if key in state:
            out.append(state[key])
    for choice in state.get("Choices", []):
        out.append(choice["Next"])
    for catch in state.get("Catch", []):
        out.append(catch["Next"])
    return out


def lint(definition: dict, must_pass_before: dict[str, list[str]]) -> list[str]:
    states = definition["States"]
    problems = []
    if definition["StartAt"] not in states:
        problems.append(f"StartAt {definition['StartAt']} is not a state")
    for name, state in states.items():
        for target in _targets(state):
            if target not in states:
                problems.append(f"{name}: target {target} does not exist")
        terminal = state.get("End") or state["Type"] in ("Succeed", "Fail")
        if not terminal and not _targets(state):
            problems.append(f"{name}: no Next and not terminal")
        if state["Type"] == "Choice" and "Default" not in state:
            problems.append(f"{name}: Choice without Default")

    graph = {name: _targets(state) for name, state in states.items()}
    reachable, stack = set(), [definition["StartAt"]]
    while stack:
        node = stack.pop()
        if node in reachable or node not in graph:
            continue
        reachable.add(node)
        stack.extend(graph[node])
    for name in states:
        if name not in reachable:
            problems.append(f"{name}: unreachable")

    # Every path from StartAt to a guarded state must pass through each required state.
    for guarded, required in must_pass_before.items():
        for req in required:
            seen, stack = set(), [definition["StartAt"]]
            while stack:
                node = stack.pop()
                if node in seen or node == req:
                    continue
                if node == guarded:
                    problems.append(f"{guarded}: reachable without passing {req}")
                    break
                seen.add(node)
                stack.extend(graph.get(node, []))
    return problems


def lint_file(path: Path) -> list[str]:
    return lint(
        json.loads(path.read_text(encoding="utf-8")),
        {"PromoteAlias": ["ValidateCorpus", "ScoreAndDecide", "AwaitClinicalSafetySignOff"],
         "StartCustomization": ["RunDatasetGate"]},
    )
