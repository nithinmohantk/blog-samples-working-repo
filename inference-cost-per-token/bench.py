"""Measure sustained output throughput of an OpenAI-compatible endpoint.

Works against vLLM (on GPU, or with the vLLM Neuron plugin on Inferentia2
and Trainium), and any server that implements streaming /v1/completions.
For each concurrency level it sends a fixed number of requests and reports
time to first token (TTFT), inter-token latency (ITL) and aggregate output
tokens per second. `best_under_slo` picks the highest throughput that still
meets your latency targets; that figure is the `tokens_per_second` input
for costmodel.Candidate.

Usage:
    python bench.py --url http://localhost:8000 --model my-model \
        --prompt-file prompts.txt --concurrency 1 4 8 16 32 --requests 64
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
from dataclasses import dataclass, field

import httpx


@dataclass
class RequestResult:
    ok: bool
    ttft: float = 0.0               # seconds to first token
    latency: float = 0.0            # seconds to last token
    output_tokens: int = 0
    gaps: list[float] = field(default_factory=list)  # seconds between streamed chunks
    error: str = ""


@dataclass
class LevelResult:
    concurrency: int
    requests: int
    failures: int
    wall_seconds: float
    output_tokens: int
    ttft_p50: float
    ttft_p95: float
    itl_p95: float

    @property
    def tokens_per_second(self) -> float:
        return self.output_tokens / self.wall_seconds if self.wall_seconds else 0.0


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    k = (len(ordered) - 1) * pct / 100
    lo, hi = int(k), min(int(k) + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


async def one_request(client: httpx.AsyncClient, url: str, model: str, prompt: str,
                      max_tokens: int) -> RequestResult:
    body = {
        "model": model,
        "prompt": prompt,
        "max_tokens": max_tokens,
        "temperature": 0,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    start = time.perf_counter()
    first = last = None
    chunks = 0
    usage_tokens = None
    gaps: list[float] = []
    try:
        async with client.stream("POST", f"{url}/v1/completions", json=body) as resp:
            if resp.status_code != 200:
                await resp.aread()
                return RequestResult(ok=False, error=f"HTTP {resp.status_code}")
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data = line[6:].strip()
                if data == "[DONE]":
                    break
                event = json.loads(data)
                if event.get("usage"):
                    usage_tokens = event["usage"].get("completion_tokens")
                choices = event.get("choices") or []
                if choices and choices[0].get("text"):
                    now = time.perf_counter()
                    if first is None:
                        first = now
                    else:
                        gaps.append(now - last)
                    last = now
                    chunks += 1
    except (httpx.HTTPError, json.JSONDecodeError) as exc:
        return RequestResult(ok=False, error=type(exc).__name__)
    if first is None:
        return RequestResult(ok=False, error="no tokens")
    return RequestResult(
        ok=True,
        ttft=first - start,
        latency=last - start,
        # Prefer the server's count; one streamed chunk can carry several tokens.
        output_tokens=usage_tokens if usage_tokens is not None else chunks,
        gaps=gaps,
    )


async def run_level(url: str, model: str, prompts: list[str], concurrency: int,
                    requests: int, max_tokens: int, timeout: float = 300.0) -> LevelResult:
    sem = asyncio.Semaphore(concurrency)
    limits = httpx.Limits(max_connections=concurrency, max_keepalive_connections=concurrency)
    async with httpx.AsyncClient(timeout=timeout, limits=limits) as client:

        async def bounded(i: int) -> RequestResult:
            async with sem:
                return await one_request(client, url, model, prompts[i % len(prompts)], max_tokens)

        start = time.perf_counter()
        results = await asyncio.gather(*(bounded(i) for i in range(requests)))
        wall = time.perf_counter() - start

    good = [r for r in results if r.ok]
    gaps = [g for r in good for g in r.gaps]
    return LevelResult(
        concurrency=concurrency,
        requests=requests,
        failures=len(results) - len(good),
        wall_seconds=wall,
        output_tokens=sum(r.output_tokens for r in good),
        ttft_p50=percentile([r.ttft for r in good], 50),
        ttft_p95=percentile([r.ttft for r in good], 95),
        itl_p95=percentile(gaps, 95),
    )


def best_under_slo(levels: list[LevelResult], ttft_p95_max: float, itl_p95_max: float,
                   max_failure_rate: float = 0.0) -> LevelResult | None:
    """Highest-throughput level that meets the latency and error targets."""
    passing = [
        lv for lv in levels
        if lv.ttft_p95 <= ttft_p95_max
        and lv.itl_p95 <= itl_p95_max
        and lv.failures <= lv.requests * max_failure_rate
    ]
    return max(passing, key=lambda lv: lv.tokens_per_second, default=None)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--url", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--prompt-file", required=True, help="one prompt per line, representative of production")
    ap.add_argument("--concurrency", type=int, nargs="+", default=[1, 4, 8, 16, 32])
    ap.add_argument("--requests", type=int, default=64)
    ap.add_argument("--max-tokens", type=int, default=256)
    ap.add_argument("--ttft-p95", type=float, default=2.0, help="seconds")
    ap.add_argument("--itl-p95", type=float, default=0.1, help="seconds")
    args = ap.parse_args()

    with open(args.prompt_file, encoding="utf-8") as fh:
        prompts = [line.strip() for line in fh if line.strip()]
    if not prompts:
        raise SystemExit("prompt file is empty")

    levels = []
    for c in args.concurrency:
        lv = asyncio.run(run_level(args.url, args.model, prompts, c, args.requests, args.max_tokens))
        levels.append(lv)
        print(f"c={c:>3} tok/s={lv.tokens_per_second:8.1f} ttft_p50={lv.ttft_p50:.2f}s "
              f"ttft_p95={lv.ttft_p95:.2f}s itl_p95={lv.itl_p95 * 1000:.0f}ms failures={lv.failures}")
    best = best_under_slo(levels, args.ttft_p95, args.itl_p95)
    if best is None:
        print("No concurrency level met the latency targets.")
    else:
        print(f"Use tokens_per_second={best.tokens_per_second:.1f} (concurrency {best.concurrency})")


if __name__ == "__main__":
    main()
