"""cache_stats.py - one shape for cache usage, whichever provider answered."""
from dataclasses import dataclass


@dataclass(frozen=True)
class CacheStats:
    uncached_input_tokens: int   # billed at the normal input rate
    cache_read_tokens: int       # billed at the discounted read rate
    cache_write_tokens: int      # billed at the write rate (Bedrock only at the time of writing)
    output_tokens: int

    @property
    def prompt_tokens(self) -> int:
        return self.uncached_input_tokens + self.cache_read_tokens + self.cache_write_tokens

    @property
    def read_ratio(self) -> float:
        """Share of the prompt served from cache. The number to alarm on."""
        return self.cache_read_tokens / self.prompt_tokens if self.prompt_tokens else 0.0
