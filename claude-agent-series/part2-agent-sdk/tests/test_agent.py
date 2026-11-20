"""Offline tests: tool handlers, the approval gate, the audit hooks and the options."""
from __future__ import annotations

import asyncio
import json

from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny

from rxagent_sdk.agent import (
    READ_TOOLS, AuditLog, build_options, build_tools, deny_all, make_can_use_tool, qualified)
from rxagent_sdk.rx_service import RxService


def run(coro):
    return asyncio.run(coro)


def handler(svc, name):
    return next(t for t in build_tools(svc) if t.name == name).handler


def test_lookup_returns_json_text():
    out = run(handler(RxService.with_sample_data(), "get_prescription")({"rx_id": "RX-1002"}))
    assert json.loads(out["content"][0]["text"])["status"] == "active" and "is_error" not in out


def test_business_error_is_an_instructive_is_error_result():
    out = run(handler(RxService.with_sample_data(), "get_prescription")({"rx_id": "RX-9999"}))
    assert out["is_error"] and "find_prescriptions" in out["content"][0]["text"]


def test_unexpected_exception_returns_only_a_reference(caplog):
    svc = RxService.with_sample_data()
    svc.get = lambda rx_id: (_ for _ in ()).throw(RuntimeError("db password=hunter2"))
    out = run(handler(svc, "get_prescription")({"rx_id": "RX-1001"}))
    assert out["is_error"] and "reference" in out["content"][0]["text"]
    assert "hunter2" not in out["content"][0]["text"] and "hunter2" in caplog.text


def test_annotations_mark_reads_and_the_state_change():
    tools = {t.name: t for t in build_tools(RxService.with_sample_data())}
    assert tools["get_prescription"].annotations.read_only_hint is True
    assert tools["cancel_prescription"].annotations.read_only_hint is False
    assert tools["cancel_prescription"].input_schema["additionalProperties"] is False


def test_cancel_is_denied_without_approval_and_allowed_with_it():
    audit = AuditLog()
    name, args = qualified("cancel_prescription"), {"rx_id": "RX-1003", "reason": "cough"}
    denied = run(make_can_use_tool(deny_all, audit)(name, args, None))
    assert isinstance(denied, PermissionResultDeny) and "Do not retry" in denied.message

    async def yes(_n, _a):
        return True
    allowed = run(make_can_use_tool(yes, audit)(name, args, None))
    assert isinstance(allowed, PermissionResultAllow) and allowed.updated_input == args
    assert [e["approved"] for e in audit.events] == [False, True]


def test_any_other_tool_reaching_the_gate_is_denied():
    result = run(make_can_use_tool(deny_all, AuditLog())("Bash", {"command": "ls"}, None))
    assert isinstance(result, PermissionResultDeny)


def test_audit_hook_redacts_free_text_and_makes_no_decision():
    audit = AuditLog()
    out = run(audit.pre_tool_use({"tool_name": qualified("cancel_prescription"),
                                  "tool_input": {"rx_id": "RX-1003", "reason": "dry cough on ramipril"}}, "toolu_1", None))
    assert out == {} and audit.events[0]["args"] == {"rx_id": "RX-1003", "reason": "<21 chars>"}


def test_options_lock_the_agent_down(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_WORKSPACE_ID", "wrkspc_test")
    o = build_options(RxService.with_sample_data(), deny_all, AuditLog(), tool_search=False)
    assert o.tools == [] and o.setting_sources == [] and o.permission_mode == "default"
    assert o.allowed_tools == READ_TOOLS and qualified("cancel_prescription") not in o.allowed_tools
    assert o.max_turns == 8 and o.max_budget_usd == 0.50 and o.effort == "medium"
    assert o.env == {"ANTHROPIC_CUSTOM_HEADERS": "anthropic-workspace-id: wrkspc_test", "ENABLE_TOOL_SEARCH": "false"}
    assert "rx" in o.mcp_servers and o.can_use_tool is not None
