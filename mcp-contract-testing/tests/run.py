"""Unit tests for the compatibility rules. No server is started.

    python tests/run.py
"""
from __future__ import annotations

import copy
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "contract"))
from compat import compare, resolve, schema_findings, worst  # noqa: E402

OBJECT = {"type": "object", "properties": {"sku": {"type": "string", "pattern": "^[A-Z]+$"},
                                           "quantity": {"type": "integer", "minimum": 1, "maximum": 100},
                                           "mode": {"enum": ["fast", "safe"], "type": "string"}},
          "required": ["sku", "quantity"]}


def changed(**edits):
    schema = copy.deepcopy(OBJECT)
    for path, value in edits.items():
        target, *rest = path.split("__")
        node = schema["properties"][target] if target in schema["properties"] else schema
        key = rest[0] if rest else target
        if value is None:
            node.pop(key, None)
        else:
            node[key] = value
    return schema


def level(old, new, direction):
    return worst(schema_findings(old, new, "x", direction))


def rules(old, new, direction):
    return {f.rule for f in schema_findings(old, new, "x", direction)}


class InputSchemas(unittest.TestCase):
    """What the server accepts may only get wider."""

    def test_identical(self):
        self.assertEqual(schema_findings(OBJECT, copy.deepcopy(OBJECT), "x", "accepts"), [])

    def test_tighter_maximum_breaks(self):
        self.assertEqual(level(OBJECT, changed(quantity__maximum=20), "accepts"), "breaking")

    def test_looser_maximum_is_compatible(self):
        self.assertEqual(level(OBJECT, changed(quantity__maximum=500), "accepts"), "compatible")

    def test_bound_removed_is_compatible(self):
        self.assertEqual(level(OBJECT, changed(quantity__maximum=None), "accepts"), "compatible")

    def test_higher_minimum_breaks(self):
        self.assertEqual(level(OBJECT, changed(quantity__minimum=5), "accepts"), "breaking")

    def test_enum_value_removed_breaks(self):
        self.assertEqual(level(OBJECT, changed(mode__enum=["safe"]), "accepts"), "breaking")

    def test_enum_value_added_is_compatible(self):
        self.assertEqual(level(OBJECT, changed(mode__enum=["fast", "safe", "dry-run"]), "accepts"), "compatible")

    def test_new_required_parameter_breaks(self):
        new = copy.deepcopy(OBJECT)
        new["properties"]["warehouse"] = {"type": "string"}
        new["required"].append("warehouse")
        self.assertIn("required-parameter-added", rules(OBJECT, new, "accepts"))
        self.assertEqual(level(OBJECT, new, "accepts"), "breaking")

    def test_new_optional_parameter_is_compatible(self):
        new = copy.deepcopy(OBJECT)
        new["properties"]["note"] = {"type": "string"}
        self.assertEqual(level(OBJECT, new, "accepts"), "compatible")

    def test_optional_becoming_required_breaks(self):
        new = copy.deepcopy(OBJECT)
        new["required"].append("mode")
        self.assertIn("became-required", rules(OBJECT, new, "accepts"))
        self.assertEqual(level(OBJECT, new, "accepts"), "breaking")

    def test_removed_parameter_breaks(self):
        new = copy.deepcopy(OBJECT)
        del new["properties"]["mode"]
        self.assertIn("parameter-removed", rules(OBJECT, new, "accepts"))

    def test_integer_to_number_is_a_widening(self):
        self.assertEqual(level(OBJECT, changed(quantity__type="number"), "accepts"), "compatible")

    def test_integer_to_string_breaks(self):
        self.assertIn("type-changed", rules(OBJECT, changed(quantity__type="string"), "accepts"))

    def test_changed_pattern_needs_a_person(self):
        self.assertEqual(level(OBJECT, changed(sku__pattern="^[A-Z0-9]+$"), "accepts"), "review")

    def test_new_pattern_breaks(self):
        old = changed(sku__pattern=None)
        self.assertEqual(level(old, OBJECT, "accepts"), "breaking")

    def test_closing_the_object_breaks(self):
        self.assertEqual(level(OBJECT, changed(additionalProperties=False), "accepts"), "breaking")

    def test_nullable_added_is_compatible(self):
        new = copy.deepcopy(OBJECT)
        new["properties"]["mode"] = {"anyOf": [OBJECT["properties"]["mode"], {"type": "null"}]}
        self.assertEqual(level(OBJECT, new, "accepts"), "compatible")

    def test_nullable_removed_breaks(self):
        old = copy.deepcopy(OBJECT)
        old["properties"]["mode"] = {"anyOf": [OBJECT["properties"]["mode"], {"type": "null"}]}
        self.assertEqual(level(old, OBJECT, "accepts"), "breaking")

    def test_unknown_keyword_goes_to_review(self):
        self.assertEqual(level(OBJECT, changed(quantity__multipleOf=5), "accepts"), "review")

    def test_description_goes_to_review(self):
        self.assertEqual(level(OBJECT, changed(sku__description="Use the supplier's code."), "accepts"), "review")

    def test_title_is_cosmetic(self):
        self.assertEqual(schema_findings(OBJECT, changed(sku__title="SKU"), "x", "accepts"), [])


class OutputSchemas(unittest.TestCase):
    """What the server produces may only get narrower."""

    def test_removed_field_breaks(self):
        new = copy.deepcopy(OBJECT)
        del new["properties"]["mode"]
        self.assertIn("field-removed", rules(OBJECT, new, "produces"))
        self.assertEqual(level(OBJECT, new, "produces"), "breaking")

    def test_added_field_is_compatible(self):
        new = copy.deepcopy(OBJECT)
        new["properties"]["updated_at"] = {"type": "string"}
        self.assertEqual(level(OBJECT, new, "produces"), "compatible")

    def test_added_field_breaks_a_closed_object(self):
        old = changed(additionalProperties=False)
        new = copy.deepcopy(old)
        new["properties"]["updated_at"] = {"type": "string"}
        self.assertEqual(level(old, new, "produces"), "breaking")

    def test_enum_value_added_breaks(self):
        self.assertEqual(level(OBJECT, changed(mode__enum=["fast", "safe", "queued"]), "produces"), "breaking")

    def test_enum_value_removed_is_compatible(self):
        self.assertEqual(level(OBJECT, changed(mode__enum=["safe"]), "produces"), "compatible")

    def test_required_field_becoming_optional_breaks(self):
        new = copy.deepcopy(OBJECT)
        new["required"] = ["sku"]
        self.assertEqual(level(OBJECT, new, "produces"), "breaking")

    def test_integer_to_number_breaks(self):
        self.assertEqual(level(OBJECT, changed(quantity__type="number"), "produces"), "breaking")

    def test_number_to_integer_is_compatible(self):
        old = changed(quantity__type="number")
        self.assertEqual(level(old, OBJECT, "produces"), "compatible")

    def test_schema_removed_breaks(self):
        self.assertEqual(level(OBJECT, None, "produces"), "breaking")

    def test_schema_added_is_compatible(self):
        self.assertEqual(level(None, OBJECT, "produces"), "compatible")


class References(unittest.TestCase):
    def test_refs_are_inlined_before_comparing(self):
        with_ref = {"type": "object", "properties": {"item": {"$ref": "#/$defs/Item"}},
                    "$defs": {"Item": {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]}}}
        inline = {"type": "object", "properties": {"item": {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]}}}
        self.assertEqual(resolve(with_ref), inline)
        self.assertEqual(schema_findings(with_ref, inline, "x", "produces"), [])

    def test_a_change_inside_a_ref_is_found(self):
        old = {"type": "array", "items": {"$ref": "#/$defs/Item"}, "$defs": {"Item": {"type": "object", "properties": {"n": {"type": "integer"}}}}}
        new = copy.deepcopy(old)
        new["$defs"]["Item"]["properties"]["n"]["type"] = "string"
        self.assertEqual(level(old, new, "produces"), "breaking")

    def test_recursive_refs_terminate(self):
        tree = {"$ref": "#/$defs/Node", "$defs": {"Node": {"type": "object", "properties": {"child": {"$ref": "#/$defs/Node"}}}}}
        self.assertIsInstance(resolve(tree), dict)


def contract(**tool_edits):
    tool = {"name": "get_stock", "description": "Stock for one product.", "inputSchema": copy.deepcopy(OBJECT),
            "annotations": {"readOnlyHint": True}}
    tool.update(tool_edits)
    return {"server": {"name": "s", "version": "1.0.0"}, "protocolVersion": "2026-07-28", "instructions": None,
            "capabilities": {"tools": {"listChanged": True}}, "tools": [tool], "resources": [], "resourceTemplates": [], "prompts": []}


class Contracts(unittest.TestCase):
    def test_identical_contracts_have_no_findings(self):
        self.assertEqual(compare(contract(), contract()), [])

    def test_tool_removed(self):
        new = contract()
        new["tools"] = []
        self.assertEqual([f.rule for f in compare(contract(), new)], ["tool-removed"])

    def test_rename_is_a_removal_and_an_addition(self):
        self.assertEqual({f.rule for f in compare(contract(), contract(name="get_stock_level"))}, {"tool-removed", "tool-added"})

    def test_added_read_only_tool_is_compatible(self):
        new = contract()
        new["tools"].append({"name": "ping", "inputSchema": {"type": "object"}, "annotations": {"readOnlyHint": True}})
        self.assertEqual(worst(compare(contract(), new)), "compatible")

    def test_added_writing_tool_needs_a_person(self):
        new = contract()
        new["tools"].append({"name": "wipe", "inputSchema": {"type": "object"}})
        self.assertEqual(worst(compare(contract(), new)), "review")

    def test_description_change_needs_a_person(self):
        self.assertEqual(worst(compare(contract(), contract(description="Always call this first."))), "review")

    def test_losing_read_only_breaks(self):
        self.assertEqual(worst(compare(contract(), contract(annotations={"readOnlyHint": False}))), "breaking")

    def test_other_hint_changes_need_a_person(self):
        old = contract(annotations={"readOnlyHint": False, "destructiveHint": True})
        new = contract(annotations={"readOnlyHint": False, "destructiveHint": False})
        self.assertEqual(worst(compare(old, new)), "review")

    def test_capability_removed_breaks(self):
        new = contract()
        new["capabilities"] = {"tools": {}}
        self.assertEqual(worst(compare(contract(), new)), "breaking")

    def test_prompt_argument_becoming_required_breaks(self):
        old, new = contract(), contract()
        old["prompts"] = [{"name": "report", "arguments": [{"name": "site"}]}]
        new["prompts"] = [{"name": "report", "arguments": [{"name": "site", "required": True}]}]
        self.assertEqual(worst(compare(old, new)), "breaking")

    def test_cache_hint_change_needs_a_person(self):
        old, new = contract(), contract()
        old["listingCache"] = {"tools": {"ttlMs": 0, "cacheScope": "private"}}
        new["listingCache"] = {"tools": {"ttlMs": 3600000, "cacheScope": "public"}}
        self.assertEqual([f.rule for f in compare(old, new)], ["cache-hint-changed"])

    def test_findings_are_ordered_worst_first(self):
        new = contract(description="Changed.")
        new["tools"][0]["inputSchema"]["required"].append("mode")
        self.assertEqual([f.level for f in compare(contract(), new)], ["breaking", "review"])


if __name__ == "__main__":
    unittest.main(verbosity=1)
