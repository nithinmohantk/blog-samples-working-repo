"""Summarise public IPv4 usage from a Cost and Usage Report (CUR) CSV.

Since 28 July 2023 the CUR carries two usage types, PublicIPv4:InUseAddress and
PublicIPv4:IdleAddress, with a Region code in front of them. They are billed from
1 February 2024. Before then they show the usage at no cost, which makes January's
report the best estimate of February's bill. lineItem/ResourceId is only filled in
when the report was set up with resource IDs included.

Reads the CSV (or .csv.gz) with the standard library. Column names are the CUR
CSV headers: lineItem/UsageType, lineItem/Operation, lineItem/ResourceId,
lineItem/UsageAmount.
"""
from __future__ import annotations

import csv
import gzip
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

from .cost import RATE_PER_HOUR

USAGE_SUFFIXES = ("PublicIPv4:InUseAddress", "PublicIPv4:IdleAddress")


def _open(path: Path):
    return gzip.open(path, "rt", newline="") if path.suffix == ".gz" else open(path, newline="")


def summarise_cur(path: str | Path) -> dict:
    """Address-hours and cost at $0.005, by usage type, by operation and by resource."""
    by_usage: dict[str, Decimal] = defaultdict(Decimal)
    by_operation: dict[str, Decimal] = defaultdict(Decimal)
    by_resource: dict[str, Decimal] = defaultdict(Decimal)
    with _open(Path(path)) as handle:
        for row in csv.DictReader(handle):
            usage_type = row.get("lineItem/UsageType", "")
            suffix = next((s for s in USAGE_SUFFIXES if usage_type.endswith(s)), None)
            if not suffix:
                continue
            hours = Decimal(row.get("lineItem/UsageAmount") or "0")
            by_usage[suffix] += hours
            by_operation[row.get("lineItem/Operation", "")] += hours
            by_resource[row.get("lineItem/ResourceId") or "(no resource id)"] += hours
    total = sum(by_usage.values(), Decimal(0))
    return {
        "address_hours": str(total),
        "cost_at_feb_2024_rate": str((total * RATE_PER_HOUR).quantize(Decimal("0.01"))),
        "by_usage_type": {k: str(v) for k, v in sorted(by_usage.items())},
        "by_operation": {k: str(v) for k, v in sorted(by_operation.items(), key=lambda kv: -kv[1])},
        "top_resources": [[k, str(v)] for k, v in sorted(by_resource.items(), key=lambda kv: -kv[1])[:10]],
    }
