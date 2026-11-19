"""OpenAI chat models as of January 2024, and the arithmetic for choosing one.

Prices are USD per 1,000 tokens from OpenAI's pricing page at the time;
check the current page before relying on them. `max_output` is the most
tokens a single response may contain, which for the 1106 models is far
smaller than the context window.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Model:
    name: str
    context: int            # tokens, input and output together
    max_output: int         # tokens per response
    cutoff: str             # training data cutoff
    input_per_1k: float
    output_per_1k: float
    json_mode: bool         # response_format={"type": "json_object"}
    vision: bool = False


MODELS = {m.name: m for m in [
    Model("gpt-3.5-turbo-1106", 16_385, 4_096, "2021-09", 0.0010, 0.0020, json_mode=True),
    Model("gpt-4", 8_192, 8_192, "2021-09", 0.03, 0.06, json_mode=False),
    Model("gpt-4-32k", 32_768, 32_768, "2021-09", 0.06, 0.12, json_mode=False),
    Model("gpt-4-1106-preview", 128_000, 4_096, "2023-04", 0.01, 0.03, json_mode=True),
    Model("gpt-4-vision-preview", 128_000, 4_096, "2023-04", 0.01, 0.03, json_mode=False, vision=True),
]}


def cost(model: str, input_tokens: int, output_tokens: int) -> float:
    m = MODELS[model]
    return input_tokens / 1000 * m.input_per_1k + output_tokens / 1000 * m.output_per_1k


def fits(model: str, input_tokens: int, max_output: int) -> bool:
    m = MODELS[model]
    return max_output <= m.max_output and input_tokens + max_output <= m.context


def monthly_cost(model: str, requests: int, input_tokens: int, output_tokens: int) -> float:
    return round(cost(model, input_tokens, output_tokens) * requests, 2)


def cheapest_that_fits(candidates: list[str], input_tokens: int, max_output: int,
                       need_json: bool = False) -> str | None:
    ok = [c for c in candidates if fits(c, input_tokens, max_output) and (MODELS[c].json_mode or not need_json)]
    return min(ok, key=lambda c: cost(c, input_tokens, max_output), default=None)
