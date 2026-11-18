"""
caching_economics.py
A small model of what prompt caching does to the input cost of a reusable prefix.
All costs are relative to sending that prefix uncached (1.0 = no change).
"""
import math
from dataclasses import dataclass


@dataclass(frozen=True)
class CachePricing:
    """Multipliers on the normal input-token price."""
    write: float          # first request, or any request after the entry expired
    read: float           # request that finds the prefix in the cache
    ttl_minutes: float    # lifetime, refreshed on every hit


# Published multipliers at the time of writing. Check the pricing pages before relying on them.
BEDROCK_CLAUDE_5M = CachePricing(write=1.25, read=0.10, ttl_minutes=5)
BEDROCK_CLAUDE_1H = CachePricing(write=2.00, read=0.10, ttl_minutes=60)


def azure_openai(discount: float, ttl_minutes: float = 5) -> CachePricing:
    """Azure OpenAI: no charge to write; reads are discounted by a model-specific fraction."""
    if not 0 <= discount <= 1:
        raise ValueError("discount must be between 0 and 1")
    return CachePricing(write=1.0, read=1.0 - discount, ttl_minutes=ttl_minutes)


def hit_probability(mean_minutes_between_requests: float, ttl_minutes: float) -> float:
    """
    Chance that a request finds a live entry, for requests on the SAME prefix arriving at
    random (Poisson) with the given mean gap. A hit needs the previous request to have
    arrived within the TTL, because every hit refreshes the entry.
    """
    if mean_minutes_between_requests <= 0:
        raise ValueError("mean gap must be positive")
    return 1.0 - math.exp(-ttl_minutes / mean_minutes_between_requests)


def relative_cost(hit_rate: float, pricing: CachePricing) -> float:
    """Average input cost of the prefix per request, relative to no caching."""
    if not 0 <= hit_rate <= 1:
        raise ValueError("hit_rate must be between 0 and 1")
    return hit_rate * pricing.read + (1 - hit_rate) * pricing.write


def break_even_hit_rate(pricing: CachePricing) -> float:
    """Hit rate above which caching is cheaper than not caching. 0.0 when a write costs no extra."""
    if pricing.write <= 1.0:
        return 0.0
    return (pricing.write - 1.0) / (pricing.write - pricing.read)


def break_even_gap_minutes(pricing: CachePricing) -> float:
    """Largest mean gap between requests at which caching still pays for itself."""
    h = break_even_hit_rate(pricing)
    return math.inf if h == 0 else -pricing.ttl_minutes / math.log(1 - h)
