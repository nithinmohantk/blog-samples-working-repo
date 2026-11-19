"""Monthly cost estimate for one S3 table, using S3 Tables price dimensions.

Rates default to AWS's published S3 Tables example for US West (Oregon) after
the July 2025 compaction price cut; pass a Rates object for other Regions.
Binpack compaction rates only: sort and z-order cost more per GB.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Rates:
    storage_gb_month: float = 0.0265        # first 50 TB, Standard
    put_per_1000: float = 0.005
    get_per_1000: float = 0.0004
    monitoring_per_1000_objects: float = 0.025
    compaction_per_1000_objects: float = 0.002
    compaction_per_gb: float = 0.005


@dataclass(frozen=True)
class Workload:
    storage_gb: float
    objects: int
    puts: int
    gets: int
    compaction_objects: int
    compaction_gb: float


def monthly_cost(w: Workload, r: Rates = Rates()) -> dict[str, float]:
    lines = {
        "storage": w.storage_gb * r.storage_gb_month,
        "put_requests": w.puts / 1000 * r.put_per_1000,
        "get_requests": w.gets / 1000 * r.get_per_1000,
        "monitoring": w.objects / 1000 * r.monitoring_per_1000_objects,
        "compaction_objects": w.compaction_objects / 1000 * r.compaction_per_1000_objects,
        "compaction_data": w.compaction_gb * r.compaction_per_gb,
    }
    lines = {k: round(v, 2) for k, v in lines.items()}
    lines["total"] = round(sum(lines.values()), 2)
    return lines
