"""Run the same prompts through several OpenAI models and compare the results.

Each request uses temperature 0 and a fixed `seed` (a beta feature of the
1106 models that makes outputs mostly reproducible; `system_fingerprint`
changes when the backend does). For JSON tasks, models that support it are
called with JSON mode. The report records answer, latency, tokens, cost and
fingerprint per model so the choice rests on your own prompts.

Usage:
    OPENAI_API_KEY=... python compare.py prompts.jsonl gpt-3.5-turbo-1106 gpt-4-1106-preview
"""
from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass

from openai import APIError, OpenAI

from models import MODELS, cost


@dataclass
class Result:
    model: str
    prompt_id: str
    answer: str | None
    latency_s: float
    input_tokens: int = 0
    output_tokens: int = 0
    fingerprint: str | None = None
    error: str | None = None

    @property
    def cost(self) -> float:
        return cost(self.model, self.input_tokens, self.output_tokens)


def run_one(client: OpenAI, model: str, prompt: dict, seed: int = 7) -> Result:
    kwargs = {
        "model": model,
        "messages": [{"role": "system", "content": prompt.get("system", "You are a precise assistant.")},
                     {"role": "user", "content": prompt["user"]}],
        "temperature": 0,
        "seed": seed,
        "max_tokens": prompt.get("max_tokens", 500),
    }
    if prompt.get("json") and MODELS[model].json_mode:
        # JSON mode requires the word "JSON" somewhere in the messages
        kwargs["response_format"] = {"type": "json_object"}
    start = time.perf_counter()
    try:
        resp = client.chat.completions.create(**kwargs)
    except APIError as exc:
        return Result(model, prompt["id"], None, time.perf_counter() - start, error=type(exc).__name__)
    elapsed = time.perf_counter() - start
    answer = resp.choices[0].message.content
    if prompt.get("json"):
        try:
            json.loads(answer or "")
        except json.JSONDecodeError:
            return Result(model, prompt["id"], answer, elapsed, resp.usage.prompt_tokens,
                          resp.usage.completion_tokens, resp.system_fingerprint, error="invalid JSON")
    return Result(model, prompt["id"], answer, elapsed, resp.usage.prompt_tokens,
                  resp.usage.completion_tokens, resp.system_fingerprint)


def compare(client: OpenAI, models: list[str], prompts: list[dict]) -> list[Result]:
    unknown = [m for m in models if m not in MODELS]
    if unknown:
        raise ValueError(f"no price data for {unknown}; add them to models.py")
    return [run_one(client, m, p) for p in prompts for m in models]


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    with open(argv[0], encoding="utf-8") as fh:
        prompts = [json.loads(line) for line in fh if line.strip()]
    client = OpenAI(max_retries=3, timeout=60)        # retries 429 and 5xx with backoff
    for r in compare(client, argv[1:], prompts):
        print(json.dumps({"model": r.model, "prompt": r.prompt_id, "latency_s": round(r.latency_s, 2),
                          "tokens": [r.input_tokens, r.output_tokens], "cost_usd": round(r.cost, 5),
                          "fingerprint": r.fingerprint, "error": r.error, "answer": r.answer}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
