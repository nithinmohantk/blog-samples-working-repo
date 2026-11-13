"""How much of a repository fits in the context window, and what a session of questions about it costs.

Nothing here calls a model. The token counts come from tiktoken; the prices come from prices.json.
"""
from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass

CACHE_MINIMUM = 1024   # a prompt shorter than this is never served from the cache
CACHE_STEP = 128       # beyond the minimum, cached tokens are counted in steps of this size


class PlainText:
    """Wraps a tiktoken encoding so that source code is always counted as ordinary text. Without this, a file
    that happens to contain the characters of a special token, such as a tokenizer test, stops the count."""

    def __init__(self, encoding):
        self._encoding = encoding

    def encode(self, text: str) -> list[int]:
        return self._encoding.encode(text, disallowed_special=())


@dataclass(frozen=True)
class Prices:
    input: float
    cached_input: float
    output: float
    context_window: int
    max_output: int

    @staticmethod
    def load(path: pathlib.Path) -> "Prices":
        data = json.loads(path.read_text(encoding="utf-8"))
        per_million = data["per_million_tokens"]
        return Prices(per_million["input"], per_million["cached_input"], per_million["output"],
                      data["context_window_tokens"], data["max_output_tokens"])

    def cost(self, input_tokens: int, cached_tokens: int, output_tokens: int) -> float:
        """Dollars for one request. Output tokens include the reasoning tokens, which are billed as output."""
        fresh = input_tokens - cached_tokens
        return (fresh * self.input + cached_tokens * self.cached_input + output_tokens * self.output) / 1_000_000


@dataclass(frozen=True)
class RepositoryCount:
    files: int
    lines: int
    tokens: int

    @property
    def tokens_per_line(self) -> float:
        return self.tokens / self.lines if self.lines else 0.0


def count_repository(root: pathlib.Path, suffixes: tuple[str, ...], encoder) -> RepositoryCount:
    """Counts every file under root with one of the suffixes, in path order, skipping anything that is not UTF-8."""
    files = lines = tokens = 0
    for path in sorted(p for p in root.rglob("*") if p.is_file() and p.suffix in suffixes and ".git" not in p.parts):
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        files += 1
        lines += text.count("\n") + (0 if text.endswith("\n") or not text else 1)
        tokens += len(encoder.encode(text))
    return RepositoryCount(files, lines, tokens)


def cacheable(prefix_tokens: int) -> int:
    """The part of an unchanged prefix that a later request can be billed for at the cached rate."""
    if prefix_tokens < CACHE_MINIMUM:
        return 0
    return prefix_tokens - (prefix_tokens - CACHE_MINIMUM) % CACHE_STEP


def room_for_output(prices: Prices, prefix_tokens: int, question_tokens: int) -> int:
    """Tokens left in the window for reasoning and the answer. Negative means the request does not fit."""
    return prices.context_window - prefix_tokens - question_tokens


@dataclass(frozen=True)
class SessionCost:
    questions: int
    without_cache: float
    with_cache: float

    @property
    def saving(self) -> float:
        return 1 - self.with_cache / self.without_cache if self.without_cache else 0.0


def session_cost(prices: Prices, prefix_tokens: int, question_tokens: int, output_tokens: int, questions: int) -> SessionCost:
    """A session is the same prefix sent with each of several questions. The first request fills the cache;
    the rest are assumed to arrive while it is still warm, which is the best case."""
    each_input = prefix_tokens + question_tokens
    cold = prices.cost(each_input, 0, output_tokens)
    warm = prices.cost(each_input, cacheable(prefix_tokens), output_tokens)
    return SessionCost(questions, cold * questions, cold + warm * (questions - 1))
