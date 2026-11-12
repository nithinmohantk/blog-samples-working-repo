"""
vector_cost_model.py
Monthly cost models for three AWS vector stores, US East (N. Virginia), prices as published in June 2026.
S3 Vectors is modelled exactly as AWS bills it. The OpenSearch Serverless and Aurora figures are
capacity estimates built from stated assumptions; treat them as planning numbers, not quotes.
"""
from dataclasses import dataclass
from math import ceil

KIB, GIB, TIB = 1024, 1024**3, 1024**4
HOURS_PER_MONTH = 730


@dataclass(frozen=True)
class Workload:
    indexes: int                     # one per tenant in a siloed design; 1 for a pooled design
    vectors_per_index: int
    dimensions: int = 1024
    key_bytes: int = 174             # 0.17 KB, as in the AWS pricing examples
    filterable_bytes: int = 1024
    non_filterable_bytes: int = 1024
    queries_per_month: int = 1_000_000
    top_k: int = 10
    monthly_write_fraction: float = 1 / 6      # share of the corpus re-embedded each month
    active_hours: float = HOURS_PER_MONTH      # hours in which any query or write arrives

    @property
    def vectors(self) -> int:
        return self.indexes * self.vectors_per_index

    @property
    def vector_bytes(self) -> int:
        return 4 * self.dimensions             # float32

    @property
    def stored_bytes_per_vector(self) -> int:
        return self.vector_bytes + self.key_bytes + self.filterable_bytes + self.non_filterable_bytes


# ---------------------------------------------------------------- Amazon S3 Vectors (exact)
S3V_STORAGE_GB, S3V_PUT_GB, S3V_QUERY_PER_M, S3V_RETURN_GB = 0.06, 0.20, 2.50, 0.01
S3V_TIERS = ((100_000, 0.004), (9_900_000, 0.002), (float("inf"), 0.0004))    # vectors in tier, $ per TB
S3V_FREE_RETURN_BYTES, S3V_MIN_RESULT_BYTES = 500 * KIB, 256


def s3_vectors(w: Workload) -> dict[str, float]:
    stored_gb = w.vectors * w.stored_bytes_per_vector / GIB
    # Query processing is billed on the size of the index a query runs against, not on the corpus.
    processed = w.vector_bytes + w.key_bytes + w.filterable_bytes        # non-filterable metadata is excluded
    remaining, processing = w.vectors_per_index, 0.0
    for tier_vectors, per_tb in S3V_TIERS:
        in_tier = min(remaining, tier_vectors)
        processing += in_tier * processed * w.queries_per_month / TIB * per_tb
        remaining -= in_tier
        if remaining <= 0:
            break
    result_bytes = max(w.key_bytes + w.filterable_bytes + w.non_filterable_bytes, S3V_MIN_RESULT_BYTES)
    billable_return = max(w.top_k * result_bytes - S3V_FREE_RETURN_BYTES, 0)
    return {
        "storage": stored_gb * S3V_STORAGE_GB,
        "writes": stored_gb * w.monthly_write_fraction * S3V_PUT_GB,
        "query_processing": processing,
        "query_requests": w.queries_per_month / 1e6 * S3V_QUERY_PER_M,
        "data_returned": billable_return * w.queries_per_month / GIB * S3V_RETURN_GB,
    }


# ---------------------------------------------------------------- OpenSearch Serverless (estimate)
OCU_HOUR, OSS_STORAGE_GB, OCU_RAM_BYTES, HNSW_M = 0.24, 0.02, 6 * GIB, 16


def hnsw_memory_bytes(w: Workload) -> float:
    """OpenSearch sizing rule for full-precision HNSW: 1.1 * (4 * d + 8 * m) bytes per vector."""
    return 1.1 * (4 * w.dimensions + 8 * HNSW_M) * w.vectors


def _half_units(amount: float) -> float:
    """Capacity is granted in half units at the low end, whole units above that."""
    return 0.5 if amount <= 0.5 else float(ceil(amount))


def opensearch_serverless(w: Workload, *, next_gen: bool, standby: bool = True,
                          compression: float = 1.0) -> dict[str, float]:
    copies = 2 if standby else 1
    search_ocus = _half_units(hnsw_memory_bytes(w) / compression / OCU_RAM_BYTES) * copies
    indexing_ocus = 0.5 * copies
    # Classic bills its minimum around the clock. Next generation bills only hours with activity.
    hours = w.active_hours if next_gen else HOURS_PER_MONTH
    return {
        "compute": (search_ocus + indexing_ocus) * hours * OCU_HOUR,
        "storage": w.vectors * w.stored_bytes_per_vector / GIB * OSS_STORAGE_GB,
    }


# ---------------------------------------------------------------- Aurora Serverless v2 + pgvector (estimate)
ACU_HOUR, AURORA_STORAGE_GB, ACU_RAM_BYTES = 0.12, 0.10, 2 * GIB


def aurora_pgvector(w: Workload, *, auto_pause: bool, min_acu: float = 0.5,
                    compression: float = 1.0) -> dict[str, float]:
    index_bytes = w.vectors * (w.vector_bytes / compression + 8 * HNSW_M * 2)   # vectors plus graph links
    table_bytes = w.vectors * w.stored_bytes_per_vector
    acus = max(_half_units(index_bytes / ACU_RAM_BYTES), min_acu)        # keep the HNSW index in memory
    idle_hours = HOURS_PER_MONTH - w.active_hours
    idle_acu = 0 if auto_pause else min_acu
    return {
        "compute": (acus * w.active_hours + idle_acu * idle_hours) * ACU_HOUR,
        "storage": (index_bytes + table_bytes) / GIB * AURORA_STORAGE_GB,   # Aurora Standard; I/O charged separately
    }


def total(parts: dict[str, float]) -> float:
    return round(sum(parts.values()), 2)
