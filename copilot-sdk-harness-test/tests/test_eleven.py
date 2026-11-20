"""The eleven scenarios as tests. No real model: a scripted OpenAI-compatible endpoint drives
the Copilot runtime. The first run downloads the runtime (about 200 MB) unless it is cached.

Hardened outcomes are asserted. Default outcomes are asserted too, as documentation of what the
SDK does out of the box with microsoft-copilot-sdk 2.0.1; if a release changes them, a test fails
and the diff is worth reading.
"""
from __future__ import annotations

import asyncio
import shutil
import tempfile

import pytest

from harness import scenarios as sc

SANDBOX_TOOLS = all(shutil.which(t) for t in ("bwrap", "slirp4netns", "ip"))


@pytest.fixture(scope="module")
def run():
    from harness import scripted_model as sm
    srv, url = sm.serve()
    sc.PORT = srv.server_address[1]
    tenant = tempfile.mkdtemp(prefix="csdk-test-")
    sc.RUNAWAY_WAIT_S = 15.0

    def _run(scenario: str, config: str):
        if scenario == "crash":
            return sc.run_crash(config, url)
        return asyncio.run(sc.run_session(scenario, config, url, tenant))[0]
    yield _run
    srv.shutdown()
    shutil.rmtree(tenant, ignore_errors=True)


def test_runaway_defaults_keep_looping_after_the_wait_ends(run):
    r = run("runaway", "defaults")
    assert r.model_calls > 100 and r.detail["model_calls_in_5s_after_wait_ended"] > 0


def test_runaway_hardened_is_stopped_by_the_budget(run):
    r = run("runaway", "hardened")
    assert r.outcome.startswith("stopped by the budget") and r.model_calls <= 14
    assert r.detail["model_calls_in_5s_after_wait_ended"] == 0


@pytest.mark.parametrize("config", ["defaults", "hardened"])
def test_wrong_arguments_are_explained_to_the_model(run, config):
    r = run("badargs", config)
    assert "order_id: Field required" in r.detail["first_tool_result"] and r.outcome == "answered"


def test_unknown_tool_lists_only_the_agents_tools_when_hardened(run):
    assert "bash" in run("unknown", "defaults").detail["first_tool_result"]
    first = run("unknown", "hardened").detail["first_tool_result"]
    assert "bash" not in first and "refund" in first


def test_flaky_tool(run):
    d = run("flaky", "defaults")
    assert d.model_calls == 4 and "internal.example" not in str(d.detail)   # the model retried; no host leak
    h = run("flaky", "hardened")
    assert h.model_calls == 2                                               # the tool retried
    assert "events" in h.detail["tool_results_seen"][-1]


def test_large_result(run):
    assert run("big", "defaults").detail["chars_sent_to_model"] < 1_000     # spilled to a temp file
    assert run("big", "hardened").detail["chars_sent_to_model"] <= 4_100    # capped in the tool


def test_slow_tool(run):
    assert run("slow", "defaults").wall_s >= 6.0
    h = run("slow", "hardened")
    assert "did not answer within 1 s" in h.detail["tool_results_seen"][-1] and h.wall_s < 6.0


def test_injected_instruction(run):
    assert [tuple(x) for x in run("inject", "defaults").detail["refunds"]] == [("B-9", 150.0)]
    h = run("inject", "hardened")
    assert h.detail["refunds"] == [] and h.detail["approver"][0][2] is False


@pytest.mark.skipif(not SANDBOX_TOOLS, reason="the runtime sandbox needs bwrap, slirp4netns and ip on Linux")
def test_generated_code(run):
    assert "sk-test-NOT-A-REAL-KEY" in run("genenv", "defaults").detail["tool_results_seen"][0]
    assert "copilot_mask_" in run("genenv", "hardened").detail["tool_results_seen"][0]
    assert "allocated" in run("genmem", "hardened").detail["tool_results_seen"][0]   # no memory limit
    assert "connected" in run("gennet", "defaults").detail["tool_results_seen"][0]
    assert "connected\n" not in run("gennet", "hardened").detail["tool_results_seen"][0]


def test_crash_after_refund(run):
    assert run("crash", "defaults").detail["ledger_rows"] == 2
    assert run("crash", "hardened").detail["ledger_rows"] == 1
