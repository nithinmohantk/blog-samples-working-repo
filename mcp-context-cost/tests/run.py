"""Unit tests for the reduction steps, the tool index and the token counter.

    python tests/run.py
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from measure.search import ToolIndex, words  # noqa: E402
from measure.slim import bare_schema, first_sentence, short_description, strip_generated  # noqa: E402
from measure.tokens import compact, count, definition, listing_cost, tool_cost  # noqa: E402

TOOL = {"name": "create_issue", "description": "Create an issue in a repository. The repository must exist.\nLabels are optional.",
        "inputSchema": {"$schema": "http://json-schema.org/draft-07/schema#", "type": "object", "title": "createIssueArguments", "required": ["title"],
                        "properties": {"title": {"type": "string", "title": "Title", "description": "Issue title."},
                                       "labels": {"type": "array", "items": {"type": "string", "title": "Label"}, "default": []}}}}


class Slimming(unittest.TestCase):
    def test_generated_fields_go_and_a_property_called_title_stays(self):
        schema = strip_generated(TOOL)["inputSchema"]
        self.assertNotIn("$schema", schema)
        self.assertNotIn("title", schema)                      # the schema's own title
        self.assertIn("title", schema["properties"])           # the parameter named title
        self.assertNotIn("title", schema["properties"]["title"])
        self.assertNotIn("title", schema["properties"]["labels"]["items"])
        self.assertEqual(schema["required"], ["title"])

    def test_the_original_is_not_modified(self):
        strip_generated(TOOL)
        self.assertIn("$schema", TOOL["inputSchema"])

    def test_first_sentence(self):
        self.assertEqual(first_sentence("Create an issue. More text."), "Create an issue.")
        self.assertEqual(first_sentence("No full stop here"), "No full stop here")
        self.assertEqual(first_sentence("Reads v1.2 files. Then stops."), "Reads v1.2 files.")
        self.assertEqual(first_sentence(""), "")

    def test_short_description_keeps_parameter_descriptions(self):
        slim = short_description(TOOL)
        self.assertEqual(slim["description"], "Create an issue in a repository.")
        self.assertEqual(slim["inputSchema"]["properties"]["title"]["description"], "Issue title.")

    def test_bare_schema_keeps_names_types_and_required(self):
        schema = bare_schema(TOOL)["inputSchema"]
        self.assertEqual(schema["properties"]["title"], {"type": "string"})
        self.assertEqual(schema["properties"]["labels"], {"type": "array", "items": {"type": "string"}})
        self.assertEqual(schema["required"], ["title"])

    def test_each_level_is_no_larger_than_the_one_before(self):
        sizes = [len(compact(definition(step(TOOL)))) for step in (lambda t: t, strip_generated, short_description, bare_schema)]
        self.assertEqual(sizes, sorted(sizes, reverse=True))


class Search(unittest.TestCase):
    TOOLS = [{"name": "git_status", "description": "Shows the working tree status.", "inputSchema": {"properties": {"repo_path": {}}}},
             {"name": "git_log", "description": "Shows the commit logs.", "inputSchema": {"properties": {"repo_path": {}, "max_count": {}}}},
             {"name": "create_issue", "description": "Create a new issue in a GitHub repository.", "inputSchema": {"properties": {"title": {}, "body": {}}}},
             {"name": "browser_click", "description": "Perform click on a web page.", "inputSchema": {"properties": {"element": {}}}}]

    def test_words_split_names_and_drop_plurals_and_stop_words(self):
        self.assertEqual(words("list_pullRequests for the repo"), ["list", "pull", "request", "repo"])

    def test_the_obvious_tool_ranks_first(self):
        index = ToolIndex(self.TOOLS)
        self.assertEqual(index.search("open an issue on github")[0]["name"], "create_issue")
        self.assertEqual(index.search("show commit log")[0]["name"], "git_log")
        self.assertEqual(index.search("click the button on the page")[0]["name"], "browser_click")

    def test_no_shared_words_means_no_results(self):
        self.assertEqual(ToolIndex(self.TOOLS).search("convert timezone"), [])

    def test_limit(self):
        self.assertEqual(len(ToolIndex(self.TOOLS).search("git show status log commit", limit=1)), 1)


class Tokens(unittest.TestCase):
    def test_counts_are_positive_and_add_up_roughly(self):
        cost = tool_cost(TOOL)
        self.assertGreater(cost["schema"], cost["description"])
        self.assertGreater(cost["total"], cost["description"] + cost["schema"])  # the wrapping costs a few tokens too
        self.assertLess(cost["total"], (cost["name"] + cost["description"] + cost["schema"]) * 1.25)

    def test_special_token_text_is_counted_not_rejected(self):
        self.assertGreater(count("<|endoftext|>"), 0)

    def test_empty_listing(self):
        self.assertEqual(listing_cost([]), 0)


if __name__ == "__main__":
    unittest.main(verbosity=1)
