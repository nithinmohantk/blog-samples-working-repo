"""Turn a simulation run's output items into a GateResult."""

from __future__ import annotations

from typing import Any, Iterator

from .checks import Failure, check_conversation
from .decide import GateResult
from .foundry import JUDGES
from .scenarios import SCENARIOS, by_id

# Judges that reward "doing what the user asked"; meaningless when the right answer is no.
NOT_FOR_REFUSALS = frozenset({"task_completion", "customer_satisfaction"})


def _walk(obj: Any) -> Iterator[Any]:
    yield obj
    if isinstance(obj, dict):
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)


def scenario_id(item: dict[str, Any]) -> str | None:
    known = by_id()
    ds = item.get("datasource_item") or {}
    if isinstance(ds, dict) and ds.get("test_case_id") in known:
        return ds["test_case_id"]
    for node in _walk(ds or item):
        if isinstance(node, dict) and isinstance(node.get("id"), str) and node["id"] in known:
            return node["id"]
    return None


def messages(item: dict[str, Any]) -> list[dict[str, Any]]:
    """Longest list of role-tagged messages anywhere in the item."""
    best: list[dict[str, Any]] = []
    for node in _walk(item.get("datasource_item", item)):
        if isinstance(node, list) and node and all(isinstance(m, dict) and "role" in m for m in node):
            if len(node) > len(best):
                best = node
    return best


def judge_results(item: dict[str, Any]) -> dict[str, bool | None]:
    out: dict[str, bool | None] = {}
    for r in item.get("results") or []:
        name = str(r.get("name", ""))
        judge = next((j for j in JUDGES if j in name), None)
        if judge is not None:
            out[judge] = r.get("passed")
    return out


def summarise(version: str, items: list[dict[str, Any]]) -> tuple[GateResult, list[dict[str, Any]]]:
    known = by_id()
    failures: list[Failure] = []
    seen: set[str] = set()
    tallies: dict[str, list[bool]] = {j: [] for j in JUDGES}
    rows: list[dict[str, Any]] = []

    for item in items:
        sid = scenario_id(item)
        msgs = messages(item)
        judged = judge_results(item)
        row_failures: list[Failure] = []
        if sid is not None:
            seen.add(sid)
            row_failures = check_conversation(known[sid], msgs)
            failures.extend(row_failures)
        refusal = sid is not None and known[sid].refusal
        excluded = sorted(NOT_FOR_REFUSALS & judged.keys()) if refusal else []
        for judge, passed in judged.items():
            if passed is not None and judge not in excluded:
                tallies[judge].append(bool(passed))
        ds = item.get("datasource_item") or {}
        rows.append(
            {
                "scenario": sid,
                "latency_ms": ds.get("target_latency_ms") if isinstance(ds, dict) else None,
                "turns": sum(1 for m in msgs if m.get("role") == "assistant"),
                "judges": judged,
                "excluded": excluded,
                "failures": [f"{f.rule}: {f.detail}" for f in row_failures],
            }
        )

    pass_rates = {j: sum(v) / len(v) for j, v in tallies.items() if v}
    result = GateResult(
        agent_version=version,
        conversations=len(items),
        pass_rates=pass_rates,
        failures=failures,
        safety_scenarios=frozenset(s.id for s in SCENARIOS if s.safety),
        missing_scenarios=[s.id for s in SCENARIOS if s.id not in seen],
    )
    return result, rows
