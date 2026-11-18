"""Count what a tool definition costs in a prompt.

A model never sees MCP's own JSON. The client turns each tool into the function-calling format of
whichever API it uses, and that is what is tokenised and billed. The three fields that carry over are
the same everywhere: a name, a description and a JSON Schema for the parameters. This module counts
those three, serialised as compact JSON, with OpenAI's published tokenisers.

It is a measure, not a bill. Each provider wraps the definitions in its own framing and uses its own
tokeniser, so the billed figure differs by some percentage in either direction. The ranking between
tools and servers, and the size of the savings, carry over; the absolute numbers are indicative.
"""
from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

import tiktoken

PRIMARY, SECONDARY = "o200k_base", "cl100k_base"


@lru_cache(maxsize=4)
def encoder(name: str):
    return tiktoken.get_encoding(name)


def count(text: str, encoding: str = PRIMARY) -> int:
    return len(encoder(encoding).encode(text, disallowed_special=()))


def compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def definition(tool: dict[str, Any]) -> dict[str, Any]:
    """The part of an MCP tool that reaches a model, in the shape function-calling APIs take."""
    return {"name": tool["name"], "description": tool.get("description", ""), "parameters": tool.get("inputSchema", {"type": "object"})}


def tool_cost(tool: dict[str, Any], encoding: str = PRIMARY) -> dict[str, int]:
    shaped = definition(tool)
    return {"total": count(compact(shaped), encoding), "name": count(shaped["name"], encoding),
            "description": count(shaped["description"], encoding), "schema": count(compact(shaped["parameters"]), encoding),
            "characters": len(compact(shaped))}


def listing_cost(tools: list[dict[str, Any]], encoding: str = PRIMARY) -> int:
    """Tokens for a whole list of definitions, serialised together as one array."""
    return count(compact([definition(tool) for tool in tools]), encoding) if tools else 0
