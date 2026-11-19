"""The harness's own regression suite. No model, no network: python -m unittest discover -s tests -t ."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from harness import sandbox
from harness.budget import Budget
from harness.loop import _compact, run_agent
from harness.model import ScriptedModel, call, last_tool_result, say, tool_results
from harness.policy import Policy
from harness.store import Store
from harness.tools import Registry, Tool

SPANS = InMemorySpanExporter()
_provider = TracerProvider()
_provider.add_span_processor(SimpleSpanProcessor(SPANS))
trace.set_tracer_provider(_provider)

ORDER = {"type": "object", "properties": {"order_id": {"type": "string", "pattern": "^O-[0-9]{4}$"}}, "required": ["order_id"], "additionalProperties": False}
REFUND = {"type": "object", "properties": {"order_id": {"type": "string"}, "amount": {"type": "number", "exclusiveMinimum": 0, "maximum": 200}},
          "required": ["order_id", "amount"], "additionalProperties": False}


class HarnessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.folder.name) / "runs.sqlite")
        self.paid: list[tuple[str, float, str]] = []
        self.registry = Registry([
            Tool("lookup_order", "Status of one order.", ORDER, lambda a, c: f"{a['order_id']}: shipped"),
            Tool("refund_order", "Refund an order.", REFUND, lambda a, c: self.paid.append((a["order_id"], a["amount"], c.idempotency_key)) or "refunded", effect="write"),
        ])
        SPANS.clear()

    def tearDown(self) -> None:
        self.store.close()
        self.folder.cleanup()

    def run_script(self, script, run_id: str = "r1", **options):
        return run_agent(ScriptedModel(script), self.registry, "task", run_id=run_id, store=self.store, **options)

    def test_a_plain_run_answers(self) -> None:
        result = self.run_script(lambda m: call("lookup_order", {"order_id": "O-1001"}, "c0") if tool_results(m) == 0 else say(last_tool_result(m)))
        self.assertEqual(("done", "O-1001: shipped", 2, 1), (result.status, result.answer, result.model_calls, result.tool_calls))

    def test_schema_problems_name_the_field(self) -> None:
        self.assertEqual([], self.registry.problems("lookup_order", {"order_id": "O-1001"}))
        problems = self.registry.problems("lookup_order", {"order_id": "1001", "extra": True})
        self.assertTrue(any(p.startswith("order_id:") for p in problems) and any("extra" in p for p in problems), problems)

    def test_arguments_that_are_not_json_come_back_as_an_error(self) -> None:
        result = self.run_script(lambda m: call("lookup_order", '{"order_id": "O-1001"', "c0") if tool_results(m) == 0 else say(last_tool_result(m)))
        self.assertIn("not valid JSON", result.answer)

    def test_a_write_needs_an_approver(self) -> None:
        script = lambda m: call("refund_order", {"order_id": "O-1001", "amount": 20}, "c0") if tool_results(m) == 0 else say(last_tool_result(m))  # noqa: E731
        self.assertIn("was not approved", self.run_script(script, "denied").answer)
        self.assertEqual([], self.paid)
        self.assertEqual("refunded", self.run_script(script, "approved", policy=Policy(approve=lambda tool, a: a["amount"] <= 50)).answer)
        self.assertEqual([("O-1001", 20, "approved:c0")], self.paid)

    def test_the_schema_is_a_limit_the_model_cannot_talk_past(self) -> None:
        script = lambda m: call("refund_order", {"order_id": "O-1001", "amount": 500}, "c0") if tool_results(m) == 0 else say(last_tool_result(m))  # noqa: E731
        self.assertIn("invalid arguments", self.run_script(script, policy=Policy(approve=lambda tool, a: True)).answer)
        self.assertEqual([], self.paid)

    def test_the_tool_call_budget_stops_a_wide_fan_out(self) -> None:
        script = lambda m: call("lookup_order", {"order_id": "O-1001"}, f"c{tool_results(m)}")  # noqa: E731
        result = self.run_script(script, budget=Budget(max_model_calls=50, max_tool_calls=3))
        self.assertEqual(("stopped: tool calls (3)", 3), (result.status, result.tool_calls))

    def test_a_finished_run_is_not_run_again(self) -> None:
        script = lambda m: call("refund_order", {"order_id": "O-1001", "amount": 20}, "c0") if tool_results(m) == 0 else say("done")  # noqa: E731
        policy = Policy(approve=lambda tool, a: True)
        self.run_script(script, "same", policy=policy)
        again = self.run_script(script, "same", policy=policy)
        self.assertEqual((1, 0, "done"), (len(self.paid), again.model_calls, again.status))

    def test_a_recorded_write_is_replayed_not_repeated(self) -> None:
        self.store.save("r9", "running", [{"role": "user", "content": "task"}, call("refund_order", {"order_id": "O-1001", "amount": 20}, "c0")])
        self.store.record_effect("r9:c0", "refunded")
        result = self.run_script(lambda m: say(last_tool_result(m)), "r9", policy=Policy(approve=lambda tool, a: True))
        self.assertEqual(("refunded", []), (result.answer, self.paid))

    def test_old_results_are_shortened_before_new_ones(self) -> None:
        messages = [{"role": "user", "content": "task"}, {"role": "tool", "tool_call_id": "a", "content": "x" * 5000}, {"role": "tool", "tool_call_id": "b", "content": "y" * 5000}]
        _compact(messages, 6000)
        self.assertLess(len(messages[1]["content"]), 300)
        self.assertEqual(5000, len(messages[2]["content"]))

    def test_spans_follow_the_genai_conventions(self) -> None:
        self.run_script(lambda m: call("nope", {}, "c0") if tool_results(m) == 0 else say("ok"))
        spans = {s.name: s for s in SPANS.get_finished_spans()}
        self.assertEqual({"invoke_agent desk", "chat scripted-1", "execute_tool nope"}, set(spans))
        tool = spans["execute_tool nope"]
        self.assertEqual(("execute_tool", "nope", "c0", "unknown_tool"), tuple(tool.attributes[k] for k in ("gen_ai.operation.name", "gen_ai.tool.name", "gen_ai.tool.call.id", "error.type")))
        self.assertEqual(spans["invoke_agent desk"].context.span_id, tool.parent.span_id)
        self.assertEqual("r1", spans["invoke_agent desk"].attributes["gen_ai.conversation.id"])

    def test_the_sandbox_has_an_empty_environment_and_a_memory_limit(self) -> None:
        os.environ["FAKE_API_KEY"] = "sk-fake-not-a-real-key-0000"
        self.assertEqual("None\n", sandbox.run_python("import os; print(os.environ.get('FAKE_API_KEY'))", mode="process"))
        with self.assertRaisesRegex(RuntimeError, "MemoryError"):
            sandbox.run_python("x = bytearray(1024**3)", mode="process")

    def test_the_sandbox_stops_a_snippet_that_does_not_end(self) -> None:
        with self.assertRaises(Exception):
            sandbox.run_python("while True: pass", timeout_s=1.0, mode="process")


if __name__ == "__main__":
    unittest.main()
