"""Offline tests for the loop: a scripted fake stands in for the Messages API."""
from __future__ import annotations

from typing import Any

from anthropic.types import Message

from rxagent.loop import Decision, LoopConfig, run
from rxagent.rx_service import RxService


def msg(stop: str, *blocks: dict[str, Any], usage: dict[str, int] | None = None) -> Message:
    return Message.model_validate({
        "id": "msg_test", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
        "stop_reason": stop, "stop_sequence": None, "content": list(blocks),
        "usage": usage or {"input_tokens": 100, "output_tokens": 20,
                           "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0},
    })


def tool_use(id_: str, name: str, **args: Any) -> dict[str, Any]:
    return {"type": "tool_use", "id": id_, "name": name, "input": args}


def text(t: str) -> dict[str, Any]:
    return {"type": "text", "text": t}


def thinking(t: str) -> dict[str, Any]:
    return {"type": "thinking", "thinking": t, "signature": "sig"}


class FakeClient:
    def __init__(self, *responses: Message) -> None:
        self.responses = list(responses)
        self.requests: list[dict[str, Any]] = []
        self.messages = self

    def create(self, **kwargs: Any) -> Message:
        self.requests.append({**kwargs, "messages": list(kwargs["messages"])})
        return self.responses.pop(0)


def test_parallel_lookups_return_results_in_request_order_and_nothing_after_them():
    client = FakeClient(
        msg("tool_use", thinking("look up both"), tool_use("t1", "get_prescription", rx_id="RX-1002"),
            tool_use("t2", "get_dispense_events", rx_id="RX-1002")),
        msg("end_turn", text("RX-1002 is active and was dispensed twice.")),
    )
    result = run(client, RxService.with_sample_data(), "Status of RX-1002?")
    assert result.outcome == "completed" and "dispensed twice" in result.text
    tool_results = client.requests[1]["messages"][-1]["content"]
    assert [r["tool_use_id"] for r in tool_results] == ["t1", "t2"]
    assert all(r["type"] == "tool_result" and not r.get("is_error") for r in tool_results)
    # the assistant turn goes back unchanged, thinking block first
    assert client.requests[1]["messages"][1]["content"][0].type == "thinking"


def test_state_change_is_refused_without_approval_and_record_is_unchanged():
    svc = RxService.with_sample_data()
    client = FakeClient(
        msg("tool_use", tool_use("t1", "cancel_prescription", rx_id="RX-1003", reason="adverse reaction")),
        msg("end_turn", text("The cancellation was not approved.")),
    )
    result = run(client, svc, "Cancel RX-1003")
    sent = client.requests[1]["messages"][-1]["content"][0]
    assert sent["is_error"] and "Not approved" in sent["content"]
    assert svc.get("RX-1003")["status"] == "active"
    assert result.turns[0].calls[0].approved is False


def test_state_change_runs_after_approval():
    svc = RxService.with_sample_data()
    seen: list[tuple[str, dict]] = []

    def approve(name: str, args: dict) -> Decision:
        seen.append((name, args))
        return Decision(True, "test")

    client = FakeClient(
        msg("tool_use", tool_use("t1", "cancel_prescription", rx_id="RX-1003", reason="adverse reaction")),
        msg("end_turn", text("Cancelled.")),
    )
    run(client, svc, "Cancel RX-1003", approver=approve)
    assert seen == [("cancel_prescription", {"rx_id": "RX-1003", "reason": "adverse reaction"})]
    assert svc.get("RX-1003")["status"] == "cancelled"


def test_business_errors_and_unknown_tools_come_back_as_instructive_is_error_results():
    client = FakeClient(
        msg("tool_use", tool_use("t1", "get_prescription", rx_id="RX-9999"), tool_use("t2", "delete_everything")),
        msg("end_turn", text("RX-9999 does not exist.")),
    )
    run(client, RxService.with_sample_data(), "Status of RX-9999?")
    r1, r2 = client.requests[1]["messages"][-1]["content"]
    assert r1["is_error"] and "find_prescriptions" in r1["content"]
    assert r2["is_error"] and "Unknown tool" in r2["content"]


def test_unexpected_exception_is_logged_and_only_a_reference_reaches_the_model(monkeypatch, caplog):
    svc = RxService.with_sample_data()
    monkeypatch.setattr(svc, "get", lambda rx_id: (_ for _ in ()).throw(RuntimeError("db password=hunter2")))
    client = FakeClient(msg("tool_use", tool_use("t1", "get_prescription", rx_id="RX-1001")),
                        msg("end_turn", text("It failed.")))
    run(client, svc, "Status of RX-1001?")
    sent = client.requests[1]["messages"][-1]["content"][0]["content"]
    assert "reference" in sent and "hunter2" not in sent
    assert "hunter2" in caplog.text  # the detail stays in your logs


def test_truncated_tool_call_is_retried_with_a_larger_budget_and_not_appended():
    client = FakeClient(
        msg("max_tokens", tool_use("t0", "get_prescription", rx_id="RX-10")),
        msg("tool_use", tool_use("t1", "get_prescription", rx_id="RX-1001")),
        msg("end_turn", text("Done.")),
    )
    result = run(client, RxService.with_sample_data(), "Status of RX-1001?", cfg=LoopConfig(max_tokens=1000))
    assert [r["max_tokens"] for r in client.requests] == [1000, 2000, 1000]
    assert result.outcome == "completed" and len(result.turns) == 2


def test_refusal_stops_the_loop_with_its_own_outcome():
    client = FakeClient(msg("refusal"))
    result = run(client, RxService.with_sample_data(), "anything")
    assert result.outcome == "refusal" and result.text == ""


def test_turn_limit_and_tool_budget_bound_the_loop():
    looping = [msg("tool_use", tool_use(f"t{i}", "get_prescription", rx_id="RX-1001")) for i in range(3)]
    result = run(FakeClient(*looping), RxService.with_sample_data(), "x", cfg=LoopConfig(max_turns=3))
    assert result.outcome == "turn_limit" and len(result.turns) == 3

    client = FakeClient(
        msg("tool_use", *[tool_use(f"t{i}", "get_prescription", rx_id="RX-1001") for i in range(3)]),
        msg("end_turn", text("Stopped.")),
    )
    run(client, RxService.with_sample_data(), "x", cfg=LoopConfig(max_tool_calls=2))
    assert all("budget" in r["content"] for r in client.requests[1]["messages"][-1]["content"])


def test_every_request_keeps_tools_system_and_caching_identical():
    client = FakeClient(
        msg("tool_use", tool_use("t1", "get_prescription", rx_id="RX-1001")),
        msg("end_turn", text("ok")),
    )
    run(client, RxService.with_sample_data(), "x")
    a, b = client.requests
    for key in ("tools", "system", "thinking", "output_config", "cache_control"):
        assert a[key] == b[key]
    assert all(t["strict"] and t["input_schema"]["additionalProperties"] is False for t in a["tools"])


def test_cost_uses_cache_prices():
    usage = {"input_tokens": 1_000_000, "output_tokens": 1_000_000,
             "cache_creation_input_tokens": 1_000_000, "cache_read_input_tokens": 1_000_000}
    result = run(FakeClient(msg("end_turn", text("hi"), usage=usage)), RxService.with_sample_data(), "x")
    assert round(result.cost_usd("claude-opus-5-5"), 2) == 4 + 20 + 5 + 0.20
