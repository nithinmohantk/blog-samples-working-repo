"""Unit tests for the stand-in's reading of a conversation and for the tools' ledger. No framework is imported.

    python tests/run.py
"""
from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lab"))
from standin import PLAN, read_chat, read_gemini  # noqa: E402


def call(identifier: str, name: str) -> dict:
    return {"id": identifier, "type": "function", "function": {"name": name, "arguments": "{}"}}


class ChatConversations(unittest.TestCase):
    def test_new_conversation(self):
        self.assertEqual(read_chat({"messages": [{"role": "system", "content": "s"}, {"role": "user", "content": "go"}]}), (set(), [], 1))

    def test_answered_call_counts_as_done(self):
        body = {"messages": [{"role": "user", "content": "go"}, {"role": "assistant", "tool_calls": [call("a", "reserve_stock")]},
                             {"role": "tool", "tool_call_id": "a", "content": "{}"}]}
        self.assertEqual(read_chat(body), ({"reserve_stock"}, [], 1))

    def test_unanswered_call_is_reported(self):
        body = {"messages": [{"role": "user", "content": "go"}, {"role": "assistant", "tool_calls": [call("a", "reserve_stock")]},
                             {"role": "tool", "tool_call_id": "a", "content": "{}"}, {"role": "assistant", "tool_calls": [call("b", "charge_card")]},
                             {"role": "user", "content": "go"}]}
        self.assertEqual(read_chat(body), ({"reserve_stock"}, ["charge_card"], 2))


class GeminiConversations(unittest.TestCase):
    def test_function_call_and_response(self):
        body = {"contents": [{"role": "user", "parts": [{"text": "go"}]}, {"role": "model", "parts": [{"functionCall": {"name": "reserve_stock", "args": {}}}]},
                             {"role": "user", "parts": [{"functionResponse": {"name": "reserve_stock", "response": {}}}]},
                             {"role": "model", "parts": [{"functionCall": {"name": "charge_card", "args": {}}}]}]}
        self.assertEqual(read_gemini(body), ({"reserve_stock"}, ["charge_card"], 1))

    def test_a_function_response_turn_is_not_a_user_message(self):
        body = {"contents": [{"role": "user", "parts": [{"functionResponse": {"name": "reserve_stock", "response": {}}}]}]}
        self.assertEqual(read_gemini(body)[2], 0)


class Plan(unittest.TestCase):
    def test_the_plan_is_three_tools_in_order(self):
        self.assertEqual([name for name, _ in PLAN], ["reserve_stock", "charge_card", "send_confirmation"])


class Ledger(unittest.TestCase):
    def load(self, version: str):
        self.directory = tempfile.TemporaryDirectory()
        os.environ.update(LAB_LEDGER=os.path.join(self.directory.name, "ledger.jsonl"), LAB_TOOLS=version, CRASH_AT="")
        import tools
        return importlib.reload(tools)

    def entries(self) -> list[dict]:
        with open(os.environ["LAB_LEDGER"], encoding="utf-8") as handle:
            return [json.loads(line) for line in handle]

    def tearDown(self):
        self.directory.cleanup()

    def test_plain_tool_acts_every_time(self):
        tools = self.load("plain")
        tools.charge_card("O-1", 100)
        tools.charge_card("O-1", 100)
        self.assertEqual([e["kind"] for e in self.entries()], ["effect", "effect"])

    def test_idempotent_tool_acts_once_and_returns_the_first_result(self):
        tools = self.load("idempotent")
        first = tools.charge_card("O-1", 100)
        second = tools.charge_card("O-1", 100)
        self.assertEqual(first, second)
        self.assertEqual([e["kind"] for e in self.entries()], ["effect", "replayed"])

    def test_the_key_is_the_business_identifier(self):
        tools = self.load("idempotent")
        tools.charge_card("O-1", 100)
        tools.charge_card("O-2", 100)  # a different order is a different charge
        self.assertEqual([e["kind"] for e in self.entries()], ["effect", "effect"])

    def test_each_tool_has_its_own_key_space(self):
        tools = self.load("idempotent")
        tools.reserve_stock("O-1", "FAS-0012", 3)
        tools.charge_card("O-1", 100)
        tools.send_confirmation("O-1", "a@example.com")
        self.assertEqual(len({e["key"] for e in self.entries()}), 3)


if __name__ == "__main__":
    unittest.main(verbosity=1)
