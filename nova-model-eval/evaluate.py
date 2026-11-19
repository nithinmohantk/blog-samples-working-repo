"""Compare Bedrock models on YOUR labelled examples: accuracy, latency and cost.

Each line of the JSONL test set is {"input": "...", "expected": "LABEL"}.
Every model gets the same system prompt and inference settings through the
Converse API, so the comparison is like for like. Prices are per million
tokens and must be filled in from the Amazon Bedrock pricing page for the
Region and inference profile you use.

Usage:
    python evaluate.py --cases cases.jsonl --system "Classify ... Reply with one word." \
        --model us.amazon.nova-micro-v1:0 --model global.amazon.nova-2-lite-v1:0
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
from dataclasses import dataclass, field

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

# USD per 1M tokens (input, output). Check the Bedrock pricing page before use;
# these are us-east-1 on-demand list prices as of March 2026.
PRICES = {
    "us.amazon.nova-micro-v1:0": (0.035, 0.14),
    "us.amazon.nova-lite-v1:0": (0.06, 0.24),
    "us.amazon.nova-pro-v1:0": (0.80, 3.20),
    "us.amazon.nova-premier-v1:0": (2.50, 12.50),
    "global.amazon.nova-2-lite-v1:0": (0.30, 2.50),
}

RETRYABLE = {"ThrottlingException", "ServiceUnavailableException", "ModelNotReadyException"}


@dataclass
class ModelReport:
    model_id: str
    cases: int = 0
    correct: int = 0
    errors: int = 0
    latencies_ms: list[int] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    mistakes: list[dict] = field(default_factory=list)

    @property
    def accuracy(self) -> float:
        answered = self.cases - self.errors
        return self.correct / answered if answered else 0.0

    @property
    def p50_ms(self) -> float:
        return statistics.median(self.latencies_ms) if self.latencies_ms else 0.0

    @property
    def p95_ms(self) -> float:
        if not self.latencies_ms:
            return 0.0
        ordered = sorted(self.latencies_ms)
        return ordered[min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))]

    def cost_usd(self, prices: dict = PRICES) -> float | None:
        if self.model_id not in prices:
            return None
        pin, pout = prices[self.model_id]
        return (self.input_tokens * pin + self.output_tokens * pout) / 1_000_000


def answer_text(response: dict) -> str:
    """Join the text blocks of a Converse response, skipping reasoning blocks."""
    blocks = response["output"]["message"]["content"]
    return "".join(b["text"] for b in blocks if "text" in b).strip()


def normalise(label: str) -> str:
    return label.strip().strip(".").upper()


def converse(client, model_id: str, system: str, text: str, max_tokens: int,
             reasoning: str | None, attempts: int = 4) -> dict:
    kwargs = {
        "modelId": model_id,
        "system": [{"text": system}],
        "messages": [{"role": "user", "content": [{"text": text}]}],
        "inferenceConfig": {"maxTokens": max_tokens, "temperature": 0.0},
    }
    if reasoning:
        # Nova 2 only. Reasoning tokens are billed as output tokens, so leave
        # room for them; temperature is omitted (see the Nova 2 user guide
        # for the inference parameters allowed with each effort level).
        kwargs["additionalModelRequestFields"] = {
            "reasoningConfig": {"type": "enabled", "maxReasoningEffort": reasoning}
        }
        kwargs["inferenceConfig"] = {"maxTokens": max(max_tokens, 4000)}
    delay = 1.0
    for attempt in range(1, attempts + 1):
        try:
            return client.converse(**kwargs)
        except ClientError as exc:
            code = exc.response["Error"]["Code"]
            if code not in RETRYABLE or attempt == attempts:
                raise
            time.sleep(delay)
            delay *= 2


def evaluate(client, model_id: str, cases: list[dict], system: str,
             max_tokens: int = 10, reasoning: str | None = None) -> ModelReport:
    report = ModelReport(model_id)
    for case in cases:
        report.cases += 1
        try:
            resp = converse(client, model_id, system, case["input"], max_tokens, reasoning)
        except ClientError as exc:
            report.errors += 1
            report.mistakes.append({"input": case["input"], "error": exc.response["Error"]["Code"]})
            continue
        got = normalise(answer_text(resp))
        report.latencies_ms.append(resp["metrics"]["latencyMs"])
        report.input_tokens += resp["usage"]["inputTokens"]
        report.output_tokens += resp["usage"]["outputTokens"]
        if got == normalise(case["expected"]):
            report.correct += 1
        else:
            report.mistakes.append({"input": case["input"], "expected": case["expected"], "got": got})
    return report


def load_cases(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        cases = [json.loads(line) for line in fh if line.strip()]
    for i, c in enumerate(cases, 1):
        if not {"input", "expected"} <= c.keys():
            raise ValueError(f"line {i}: needs 'input' and 'expected'")
    return cases


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cases", required=True)
    ap.add_argument("--system", required=True)
    ap.add_argument("--model", action="append", required=True)
    ap.add_argument("--reasoning", choices=["low", "medium", "high"], help="Nova 2 models only")
    ap.add_argument("--region", default="us-east-1")
    args = ap.parse_args()

    client = boto3.client("bedrock-runtime", region_name=args.region,
                          config=Config(retries={"mode": "standard", "max_attempts": 3},
                                        read_timeout=120))
    cases = load_cases(args.cases)
    for model_id in args.model:
        r = evaluate(client, model_id, cases, args.system,
                     reasoning=args.reasoning if "nova-2" in model_id else None)
        cost = r.cost_usd()
        per_1k = f"${cost / r.cases * 1000:.4f}" if cost is not None and r.cases else "price unknown"
        print(f"{model_id:<34} accuracy={r.accuracy:.1%} errors={r.errors} "
              f"p50={r.p50_ms:.0f}ms p95={r.p95_ms:.0f}ms cost per 1k cases={per_1k}")


if __name__ == "__main__":
    main()
