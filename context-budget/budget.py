"""Plan a prompt against a model's context window before you send it.

A context window is shared by everything in the request and the response:
system prompt, user input, conversation history, retrieved documents, tool
definitions, and the tokens the model will generate. This module reserves
space for the output, places the parts that must be sent whole, and then
divides what is left between flexible sections by priority, packing each
section's items in its own order (newest turns first for history, highest
score first for retrieved passages).

Token counting is injected. Use the tokenizer of the model you call (for
example tiktoken's o200k_base for GPT-4o or cl100k_base for GPT-4 Turbo);
the tests use a whitespace counter so they run anywhere.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

Counter = Callable[[str], int]


@dataclass
class Item:
    text: str
    score: float = 0.0          # relevance, for retrieved passages
    order: int = 0              # position in time, for conversation turns


@dataclass
class Section:
    name: str
    items: list[Item]
    weight: float = 1.0         # share of the flexible space relative to other sections
    min_tokens: int = 0         # guaranteed before weights apply
    max_tokens: int | None = None
    keep: str = "best"          # "best" = highest score first, "newest" = latest order first


@dataclass
class Plan:
    window: int
    output_reserve: int
    fixed_tokens: int
    sections: dict[str, list[Item]] = field(default_factory=dict)
    used: dict[str, int] = field(default_factory=dict)
    dropped: dict[str, int] = field(default_factory=dict)

    @property
    def prompt_tokens(self) -> int:
        return self.fixed_tokens + sum(self.used.values())

    @property
    def headroom(self) -> int:
        return self.window - self.output_reserve - self.prompt_tokens


class BudgetError(ValueError):
    pass


def _ordered(section: Section) -> list[Item]:
    if section.keep == "newest":
        return sorted(section.items, key=lambda i: i.order, reverse=True)
    if section.keep == "best":
        return sorted(section.items, key=lambda i: i.score, reverse=True)
    raise ValueError(f"{section.name}: keep must be 'best' or 'newest'")


def _allocate(space: int, sections: list[Section]) -> dict[str, int]:
    """Give each section its minimum, then share the rest by weight, respecting maximums."""
    mins = sum(s.min_tokens for s in sections)
    if mins > space:
        raise BudgetError(f"section minimums need {mins} tokens but only {space} are free")
    alloc = {s.name: s.min_tokens for s in sections}
    remaining = space - mins
    open_ = [s for s in sections if s.max_tokens is None or alloc[s.name] < s.max_tokens]
    while remaining > 0 and open_:
        total_w = sum(s.weight for s in open_)
        given = 0
        for s in open_:
            share = int(remaining * s.weight / total_w)
            cap = (s.max_tokens - alloc[s.name]) if s.max_tokens is not None else share
            add = min(share, cap)
            alloc[s.name] += add
            given += add
        remaining -= given
        open_ = [s for s in open_ if s.max_tokens is None or alloc[s.name] < s.max_tokens]
        if given == 0:
            break                                   # rounding left a few tokens; stop
    return alloc


def plan(window: int, output_reserve: int, fixed: list[str], flexible: list[Section],
         count: Counter, per_message_overhead: int = 0) -> Plan:
    """Fit `fixed` texts whole and pack `flexible` sections into the remaining space.

    `per_message_overhead` adds the provider's framing tokens per message
    (chat formats wrap each message in a few tokens); check your provider.
    """
    if output_reserve <= 0 or output_reserve >= window:
        raise BudgetError("output_reserve must be positive and smaller than the window")
    fixed_tokens = sum(count(t) + per_message_overhead for t in fixed)
    space = window - output_reserve - fixed_tokens
    if space < 0:
        raise BudgetError(f"fixed content needs {fixed_tokens} tokens; only "
                          f"{window - output_reserve} fit after reserving {output_reserve} for output")
    result = Plan(window, output_reserve, fixed_tokens)
    for name, budget in _allocate(space, flexible).items():
        section = next(s for s in flexible if s.name == name)
        kept, used = [], 0
        for item in _ordered(section):
            cost = count(item.text) + per_message_overhead
            if used + cost <= budget:
                kept.append(item)
                used += cost
        if section.keep == "newest":
            kept.sort(key=lambda i: i.order)        # send history in chronological order
        result.sections[name] = kept
        result.used[name] = used
        result.dropped[name] = len(section.items) - len(kept)
    return result
