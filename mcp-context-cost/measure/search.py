"""Two ways to defer tool definitions: a search tool over an index, and a catalogue with load-by-name.

Ranking is BM25 over the words in each tool's name, description and parameter names. No embedding
model and no service: the point of the lab is to measure the trade, and the trade exists with any
retriever. A better retriever moves the hit rate; it does not change the accounting.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any

WORD = re.compile(r"[A-Za-z][a-z]+|[A-Z]+(?![a-z])|\d+")
STOP = frozenset("a an the of to in on for and or with by from is are be this that it as at into".split())

SEARCH_TOOL = {
    "name": "search_tools",
    "description": "Find tools by what they do. Returns the full definitions of the best matches, which can then be called.",
    "inputSchema": {"type": "object", "required": ["query"],
                    "properties": {"query": {"type": "string", "description": "What you need to do, in a few words."},
                                   "limit": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5}}},
}

LOAD_TOOL = {
    "name": "load_tools",
    "description": "Load the full definitions of tools from the catalogue by exact name, so that they can be called.",
    "inputSchema": {"type": "object", "required": ["names"], "properties": {"names": {"type": "array", "items": {"type": "string"}, "maxItems": 10}}},
}


def catalogue(tools: list[dict[str, Any]], with_summary: bool) -> str:
    """A compact list of every tool for the prompt: its name, and optionally the first sentence of its description."""
    lines = []
    for tool in tools:
        summary = tool.get("description", "").strip().replace("\n", " ").split(". ")[0].rstrip(".") if with_summary else ""
        lines.append(f"{tool['server']}.{tool['name']}" + (f": {summary}" if summary else ""))
    return "\n".join(lines)


def words(text: str) -> list[str]:
    found = [w.lower() for w in WORD.findall(text.replace("_", " ").replace("-", " "))]
    return [w[:-1] if len(w) > 3 and w.endswith("s") else w for w in found if w.lower() not in STOP]


def document(tool: dict[str, Any]) -> list[str]:
    parameters = " ".join((tool.get("inputSchema") or {}).get("properties", {}).keys())
    return words(tool["name"]) * 3 + words(tool.get("description", "")) + words(parameters)  # the name counts three times


class ToolIndex:
    def __init__(self, tools: list[dict[str, Any]], k1: float = 1.5, b: float = 0.75) -> None:
        self.tools, self.k1, self.b = tools, k1, b
        self.documents = [Counter(document(tool)) for tool in tools]
        self.lengths = [sum(doc.values()) for doc in self.documents]
        self.average = sum(self.lengths) / max(len(self.lengths), 1)
        spread = Counter(term for doc in self.documents for term in doc)
        self.idf = {term: math.log(1 + (len(tools) - n + 0.5) / (n + 0.5)) for term, n in spread.items()}

    def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        terms, scored = words(query), []
        for index, doc in enumerate(self.documents):
            score = 0.0
            for term in terms:
                frequency = doc.get(term, 0)
                if frequency:
                    norm = frequency + self.k1 * (1 - self.b + self.b * self.lengths[index] / self.average)
                    score += self.idf[term] * frequency * (self.k1 + 1) / norm
            if score > 0:
                scored.append((score, index))
        scored.sort(key=lambda pair: (-pair[0], pair[1]))
        return [self.tools[index] for _, index in scored[:limit]]
