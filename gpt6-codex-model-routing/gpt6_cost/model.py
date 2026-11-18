"""What requests and agent sessions cost on the GPT-6 family, from the published prices.

Nothing here calls a model. Three rules from the price list do most of the work:
  * tokens read from the prompt cache cost a tenth of the input price;
  * tokens written to the cache cost 1.25 times the input price, in place of it;
  * a request with more than 272,000 input tokens is charged double for input and cache, and one and a half
    times for output, on the whole request.
"""
from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass


@dataclass(frozen=True)
class Model:
    name: str
    input: float
    cache_read: float
    cache_write: float
    output: float


@dataclass(frozen=True)
class PriceList:
    models: dict[str, Model]
    long_context_over: int
    long_input_multiplier: float
    long_output_multiplier: float
    processing: dict[str, float]
    cache_minimum: int
    context_window: int

    @staticmethod
    def load(path: pathlib.Path) -> "PriceList":
        data = json.loads(path.read_text(encoding="utf-8"))
        long = data["long_context"]
        return PriceList(
            {name: Model(name, **prices) for name, prices in data["models"].items()},
            long["over_input_tokens"], long["input_and_cache_multiplier"], long["output_multiplier"],
            data["processing_multipliers"], data["cache_minimum_tokens"], data["context_window_tokens"])

    def request(self, model: str, uncached: int, read: int, written: int, output: int, processing: str = "standard") -> float:
        """Dollars for one request. The three input figures are disjoint and add up to the prompt."""
        prices = self.models[model]
        long = uncached + read + written > self.long_context_over
        input_cost = (uncached * prices.input + read * prices.cache_read + written * prices.cache_write) * (self.long_input_multiplier if long else 1)
        output_cost = output * prices.output * (self.long_output_multiplier if long else 1)
        return (input_cost + output_cost) * self.processing[processing] / 1_000_000


@dataclass(frozen=True)
class Turn:
    number: int
    context: int
    read: int
    written: int
    cost: float
    compacted: bool


@dataclass(frozen=True)
class Session:
    turns: list[Turn]

    @property
    def cost(self) -> float:
        return sum(turn.cost for turn in self.turns)

    @property
    def largest_context(self) -> int:
        return max(turn.context for turn in self.turns)

    @property
    def turns_over(self) -> int:
        return sum(1 for turn in self.turns if turn.context > 272_000)

    @property
    def compactions(self) -> int:
        return sum(1 for turn in self.turns if turn.compacted)


def agent_session(prices: PriceList, model: str, *, base: int, added_per_turn: int, output_per_turn: int, turns: int,
                  caching: bool = True, compact_at: int | None = None, summary: int = 20_000) -> Session:
    """An agent loop as a coding agent runs it: a fixed base (instructions, tool definitions, project notes), then
    one request per step, each carrying everything so far plus the latest tool result.

    With caching, each request reads what the previous one sent and writes what is new, which is how the default
    cache mode of these models behaves when steps follow each other within the cache lifetime. Without caching,
    every token is ordinary input, which is what a request gets in explicit mode with no breakpoint.

    compact_at replaces the history with a summary once the context passes that size. Producing the summary is
    charged as one more request. Afterwards the base is still cached; the summary is new and has to be written.
    """
    history = 0
    cached = 0
    result: list[Turn] = []
    for number in range(1, turns + 1):
        history += added_per_turn
        compacted = False
        extra = 0.0
        if compact_at is not None and base + history > compact_at:
            # The summary is itself a request. Codex sends it without its tool declarations, so it does not begin
            # like the requests before it and cannot be read from the cache: the whole conversation is new input.
            so_far = base + history - added_per_turn
            extra = prices.request(model, 0 if caching else so_far, 0, so_far if caching else 0, summary)
            history = summary + added_per_turn
            cached = min(cached, base)
            compacted = True
        context = base + history
        if caching and context >= prices.cache_minimum:
            read, written, uncached = cached, context - cached, 0
            cached = context
        else:
            read, written, uncached = 0, 0, context
        result.append(Turn(number, context, read, written, extra + prices.request(model, uncached, read, written, output_per_turn), compacted))
        history += output_per_turn   # the model's own output is part of the next request
    return Session(result)


def write_share_break_even(model: Model) -> float:
    """If a share w of prompt tokens are cache writes and the rest are reads, caching costs the same as no
    caching when w * write + (1 - w) * read = input. Above this share, caching costs more than it saves."""
    return (model.input - model.cache_read) / (model.cache_write - model.cache_read)
