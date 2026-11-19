"""Cost per million output tokens for self-hosted LLM inference.

The inputs are what you measure, not what a datasheet promises:
the instance price, the number of model replicas the instance holds,
the sustained output throughput of one replica at your latency target,
and how busy the fleet really is.
"""
from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class Candidate:
    """One way of serving the model, for example inf2.48xlarge with 2 replicas."""

    name: str
    hourly_usd: float           # price you pay per instance-hour (on-demand or committed)
    replicas_per_instance: int  # model copies the instance holds (tensor parallel groups)
    tokens_per_second: float    # output tokens/s for ONE replica at the latency target

    def __post_init__(self) -> None:
        if self.hourly_usd <= 0:
            raise ValueError(f"{self.name}: hourly_usd must be positive")
        if self.replicas_per_instance < 1:
            raise ValueError(f"{self.name}: replicas_per_instance must be at least 1")
        if self.tokens_per_second <= 0:
            raise ValueError(f"{self.name}: tokens_per_second must be positive")

    @property
    def instance_tokens_per_hour(self) -> float:
        return self.tokens_per_second * self.replicas_per_instance * 3600


def cost_per_million(c: Candidate, utilisation: float = 1.0) -> float:
    """USD per million output tokens at the given average utilisation (0 < u <= 1).

    Utilisation is the share of paid capacity that does useful work. An
    endpoint sized for a daytime peak and idle at night may average 0.3.
    """
    if not 0 < utilisation <= 1:
        raise ValueError("utilisation must be in (0, 1]")
    return c.hourly_usd / (c.instance_tokens_per_hour * utilisation) * 1_000_000


def instances_needed(c: Candidate, peak_tokens_per_second: float, headroom: float = 0.2) -> int:
    """Instances required to serve a peak output rate with spare headroom."""
    if peak_tokens_per_second <= 0:
        raise ValueError("peak_tokens_per_second must be positive")
    if not 0 <= headroom < 1:
        raise ValueError("headroom must be in [0, 1)")
    per_instance = c.tokens_per_second * c.replicas_per_instance * (1 - headroom)
    return max(1, math.ceil(peak_tokens_per_second / per_instance))


def monthly_cost(c: Candidate, instances: int, hours: float = 730.0) -> float:
    return c.hourly_usd * instances * hours


def compare(candidates: list[Candidate], peak_tokens_per_second: float,
            monthly_tokens: float, headroom: float = 0.2) -> list[dict]:
    """Rank candidates by monthly cost for a fleet sized to the peak.

    Effective utilisation follows from the sizing: tokens actually produced
    divided by the capacity you pay for.
    """
    rows = []
    for c in candidates:
        n = instances_needed(c, peak_tokens_per_second, headroom)
        cost = monthly_cost(c, n)
        capacity = c.instance_tokens_per_hour * n * 730.0
        util = min(1.0, monthly_tokens / capacity)
        rows.append({
            "name": c.name,
            "instances": n,
            "monthly_usd": round(cost, 2),
            "utilisation": round(util, 3),
            "usd_per_million": round(cost / monthly_tokens * 1_000_000, 2),
        })
    return sorted(rows, key=lambda r: r["monthly_usd"])
