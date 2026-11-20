"""Offline tests: a scripted fake of client.beta.messages stands in for the API (anthropic 2.6.0 types)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from anthropic.types.beta import BetaMessage

from auditagent.__main__ import score
from auditagent.data import expected_findings, generate
from auditagent.loop import LongRunConfig, RunState, billed_usage, run
from auditagent.service import AuditError, AuditService

import pytest


def msg(stop: str, *blocks: dict[str, Any], usage: dict[str, Any] | None = None) -> BetaMessage:
    return BetaMessage.model_validate({
        "id": "msg_t", "type": "message", "role": "assistant", "model": "claude-fable-5-2",
        "stop_reason": stop, "stop_sequence": None, "content": list(blocks),
        "usage": usage or {"input_tokens": 50, "output_tokens": 20,
                           "cache_creation_input_tokens": 0, "cache_read_input_tokens": 1000}})


def use(id_: str, name: str, **inp: Any) -> dict[str, Any]:
    return {"type": "tool_use", "id": id_, "name": name, "input": inp}


def think(t: str) -> dict[str, Any]:
    return {"type": "thinking", "thinking": t, "signature": "sig"}


class Fake:
    def __init__(self, *responses: BetaMessage) -> None:
        self.responses = list(responses)
        self.requests: list[dict[str, Any]] = []
        self.beta = self
        self.messages = self

    def create(self, **kw: Any) -> BetaMessage:
        self.requests.append(json.loads(json.dumps({**kw}, default=str)))
        return self.responses.pop(0)


def cfg(**kw: Any) -> LongRunConfig:
    return LongRunConfig(**{"compact_at_tokens": 10_000_000, **kw})


def test_history_is_append_only_and_thinking_goes_back_unchanged(tmp_path: Path):
    svc = AuditService.with_sample_data()
    client = Fake(msg("tool_use", think("start"), use("t1", "get_progress")),
                  msg("tool_use", use("t2", "get_details", rx_ids=["RX-2001", "RX-2002"])),
                  msg("end_turn", {"type": "text", "text": "done"}))
    svc.reviewed = set(svc.prescriptions)  # nothing remaining, so end_turn completes
    result = run(client, svc, cfg(), tmp_path / "s.json")
    assert result.outcome == "completed"
    first, second, third = (r["messages"] for r in client.requests)
    assert second[:len(first)] == first and third[:len(second)] == second   # prefix never changes
    assert second[1]["content"][0] == {"type": "thinking", "thinking": "start", "signature": "sig"}
    assert all(r["betas"] == ["compact-2026-09-04"] for r in client.requests)
    assert client.requests[0]["thinking"] == {"type": "adaptive"} and client.requests[0]["output_config"] == {"effort": "high"}


def test_compaction_replaces_history_with_the_signed_block_and_counts_its_cost(tmp_path: Path):
    svc = AuditService.with_sample_data()
    big = {"input_tokens": 100, "output_tokens": 100, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 60_000}
    comp_usage = {"input_tokens": 0, "output_tokens": 0, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
                  "iterations": [{"type": "compaction", "input_tokens": 2000, "output_tokens": 800,
                                  "cache_creation_input_tokens": 0, "cache_read_input_tokens": 58_000}]}
    client = Fake(msg("tool_use", use("t1", "get_progress"), usage=big),
                  msg("compaction", {"type": "compaction", "content": "Summary: 8 reviewed.", "signature": "s1"},
                      usage=comp_usage),
                  msg("end_turn", {"type": "text", "text": "done"}))
    svc.reviewed = set(svc.prescriptions)
    result = run(client, svc, cfg(compact_at_tokens=40_000), tmp_path / "s.json")
    comp_req, after = client.requests[1], client.requests[2]
    assert comp_req["compaction"]["type"] == "summarize" and "Do not call any tools" in comp_req["compaction"]["instructions"]
    assert after["messages"][0] == {"role": "assistant", "content": [
        {"type": "compaction", "content": "Summary: 8 reviewed.", "signature": "s1"}]}
    assert "get_progress" in after["messages"][1]["content"]
    assert result.state.compactions == 1
    assert result.state.usage.output == 100 + 800 + 20       # compaction output is billed and counted


def test_a_compaction_without_a_summary_keeps_the_history(tmp_path: Path):
    svc = AuditService.with_sample_data()
    svc.reviewed = set(svc.prescriptions)
    big = {"input_tokens": 100, "output_tokens": 100, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 60_000}
    client = Fake(msg("tool_use", use("t1", "get_progress"), usage=big),
                  msg("tool_use", use("x", "get_progress")),          # the model called a tool instead
                  msg("end_turn", {"type": "text", "text": "done"}))
    result = run(client, svc, cfg(compact_at_tokens=40_000), tmp_path / "s.json")
    assert result.state.compactions == 0
    assert client.requests[2]["messages"][:3] == client.requests[1]["messages"][:3]
    assert any(e["event"] == "compaction_skipped" for e in result.state.events)


def test_stop_and_resume_continue_from_the_checkpoint_with_identical_history(tmp_path: Path):
    path = tmp_path / "s.json"
    svc = AuditService.with_sample_data()
    first = Fake(msg("tool_use", use("t1", "mark_reviewed", rx_ids=["RX-2001"])),
                 msg("tool_use", use("t2", "get_progress")))
    r1 = run(first, svc, cfg(stop_after_turns=2), path)
    assert r1.outcome == "stopped" and path.exists()

    svc2 = AuditService.with_sample_data()
    state, model = RunState.load(path, svc2)
    assert model == "claude-fable-5-2" and svc2.reviewed == {"RX-2001"} and state.turns == 2
    svc2.reviewed = set(svc2.prescriptions)
    second = Fake(msg("end_turn", {"type": "text", "text": "done"}))
    r2 = run(second, svc2, cfg(), path, state)
    assert r2.outcome == "completed" and r2.state.turns == 3
    assert second.requests[0]["messages"] == json.loads(json.dumps(r1.state.messages))


def test_an_early_end_turn_is_nudged_while_work_remains(tmp_path: Path):
    svc = AuditService.with_sample_data()
    client = Fake(msg("end_turn", {"type": "text", "text": "I have done enough."}),
                  msg("tool_use", use("t1", "mark_reviewed", rx_ids=sorted(svc.prescriptions)[:4])),
                  msg("end_turn", {"type": "text", "text": "stopping"}))
    client.responses.append(msg("end_turn", {"type": "text", "text": "x"}))
    result = run(client, svc, cfg(max_turns=4), tmp_path / "s.json")
    assert any(e["event"] == "nudged" for e in result.state.events)
    assert "not finished" in client.requests[1]["messages"][-1]["content"]
    assert result.outcome == "turn_limit"


def test_budget_stops_the_run(tmp_path: Path):
    svc = AuditService.with_sample_data()
    pricey = {"input_tokens": 0, "output_tokens": 200_000, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}
    client = Fake(msg("tool_use", use("t1", "get_progress"), usage=pricey))
    result = run(client, svc, cfg(budget_usd=4.0), tmp_path / "s.json")
    assert result.outcome == "budget" and len(client.requests) == 1   # 200k output at $40/M = $8


def test_service_rules():
    svc = AuditService.with_sample_data()
    with pytest.raises(AuditError):
        svc.details(["RX-2001"] * 5)
    with pytest.raises(AuditError):  # a bad item rejects the whole batch
        svc.record([{"rx_id": "RX-2001", "rule": "STALE", "note": ""}, {"rx_id": "RX-2001", "rule": "OLD", "note": ""}])
    assert svc.findings == {}
    assert svc.record([{"rx_id": "RX-2001", "rule": "STALE", "note": "a"}])["added"] == 1
    assert svc.record([{"rx_id": "RX-2001", "rule": "STALE", "note": "b"}])["already_recorded"] == 1


def test_answer_key_and_score():
    rx, d = generate()
    expected = expected_findings(rx, d)
    assert len(rx) == 48 and len(expected) == 56
    svc = AuditService(rx, d)
    some = sorted(expected)[:10]
    svc.findings = {k: "" for k in some} | {("RX-2001", "DUPLICATE_CLASS"): ""}
    sc = score(svc)
    assert sc["ALL"]["correct"] == len(set(some)) and sc["ALL"]["expected"] == 56
    assert ["RX-2001", "DUPLICATE_CLASS"] in sc["extra"] or ("RX-2001", "DUPLICATE_CLASS") in expected


def test_billed_usage_sums_iterations():
    m = msg("end_turn", usage={"input_tokens": 10, "output_tokens": 5, "cache_creation_input_tokens": 0,
                               "cache_read_input_tokens": 0, "iterations": [
        {"type": "compaction", "input_tokens": 100, "output_tokens": 50, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0},
        {"type": "message", "input_tokens": 10, "output_tokens": 5, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}]})
    u = billed_usage(m.usage)
    assert (u.input, u.output) == (110, 55)
