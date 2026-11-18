"""On-demand prices on Amazon Bedrock, US East (N. Virginia), per 1,000 tokens, March 2024."""
from __future__ import annotations

from decimal import Decimal

PRICES = {  # model: (input, output) USD per 1,000 tokens
    "Claude Instant 1.2": (Decimal("0.0008"), Decimal("0.0024")),
    "Claude 2.0 / 2.1": (Decimal("0.008"), Decimal("0.024")),
    "Claude 3 Sonnet": (Decimal("0.003"), Decimal("0.015")),
    "Claude 3 Haiku": (Decimal("0.00025"), Decimal("0.00125")),
}


def monthly(model: str, input_tokens: int, output_tokens: int) -> Decimal:
    price_in, price_out = PRICES[model]
    return (price_in * input_tokens / 1000 + price_out * output_tokens / 1000).quantize(Decimal("0.01"))
