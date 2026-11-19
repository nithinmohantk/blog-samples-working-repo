"""Run one scenario once, in this process, and print one line of JSON about how it ended.

Usage: python -m lab.one <scenario> <bare|hardened> <work directory> <probe host> <probe port>
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from harness.bare import run_bare
from harness.loop import run_agent
from harness.model import ScriptedModel
from harness.policy import Policy
from harness.store import Store
from harness.tools import Registry
from lab.scenarios import FAKE_KEY, ledger, make_tools, scenarios


def main(name: str, mode: str, work: Path, host: str, port: int) -> None:
    os.environ["FAKE_API_KEY"] = FAKE_KEY
    scenario = scenarios((host, port))[name]
    bare_tools, hardened_tools = make_tools(work, (host, port))
    model = ScriptedModel(scenario.script)
    spans = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(spans))
    trace.set_tracer_provider(provider)

    started = time.monotonic()
    ended, answer = "", ""
    try:
        if mode == "bare":
            answer = run_bare(model, bare_tools, scenario.task)
            ended = "answered"
        else:
            result = run_agent(model, Registry(hardened_tools), scenario.task, run_id=f"run-{name}",
                               store=Store(work / "runs.sqlite"), policy=Policy(approve=scenario.approver))
            answer, ended = result.answer, "answered" if result.status == "done" else result.status
    except Exception as error:  # noqa: BLE001 - the lab reports how the run ended, whatever it was
        ended = f"crashed: {type(error).__name__}" if "lab cap" not in str(error) else "still looping after 500 model calls"

    print(json.dumps({
        "ended": ended,
        "answer": answer[:200],
        "seconds": round(time.monotonic() - started, 1),
        "model_calls": model.calls,
        "largest_request_chars": model.largest_request_chars,
        "refunds": [[entry["order_id"], entry["amount"]] for entry in ledger(work)],
        "leaked_key": FAKE_KEY in answer,
        "spans": [[s.name, s.attributes.get("error.type", ""), len(s.events), dict(s.attributes).get("harness.replayed", False)] for s in spans.get_finished_spans()],
    }))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], Path(sys.argv[3]), sys.argv[4], int(sys.argv[5]))
