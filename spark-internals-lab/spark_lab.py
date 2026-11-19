"""Small, testable helpers for looking inside Spark jobs (PySpark 4.0).

- `physical_plan`: the executed physical plan as text, after Adaptive Query
  Execution (AQE) has run, so you can see Exchanges (shuffles) and the join
  strategy Spark actually chose.
- `count_exchanges`, `join_strategy`: read those facts from the plan.
- `partition_skew`: rows per partition and the max/median ratio, to spot
  skew before it becomes one straggling task.
- `executor_memory`: the unified memory model arithmetic for an executor.

Uses the classic (non-Connect) PySpark API, which exposes the JVM query
execution; Spark Connect clients would read the same plan from the UI or
`df.explain(mode="formatted")`.
"""
from __future__ import annotations

import re
import statistics
from dataclasses import dataclass

from pyspark.sql import DataFrame, functions as F

RESERVED_MB = 300            # fixed by Spark for internal objects


def physical_plan(df: DataFrame) -> str:
    """Executed plan after an action, including AQE's final decisions."""
    qe = df._jdf.queryExecution()
    qe.toRdd().count()                                  # run this exact plan so AQE finalises it
    return qe.executedPlan().toString()


def count_exchanges(plan: str) -> int:
    """Shuffle exchanges in a plan (broadcast exchanges are not shuffles)."""
    return len(re.findall(r"(?<![A-Za-z])Exchange\b", plan))


def join_strategy(plan: str) -> str | None:
    for name in ("BroadcastHashJoin", "SortMergeJoin", "ShuffledHashJoin", "BroadcastNestedLoopJoin",
                 "CartesianProduct"):
        if name in plan:
            return name
    return None


@dataclass
class Skew:
    rows_per_partition: list[int]

    @property
    def ratio(self) -> float:
        nonzero = [r for r in self.rows_per_partition if r] or [0]
        median = statistics.median(nonzero)
        return max(nonzero) / median if median else 0.0


def partition_skew(df: DataFrame, key: str, partitions: int) -> Skew:
    """Rows per partition if `df` were hash-partitioned on `key` into `partitions`."""
    counts = (df.repartition(partitions, key)
                .groupBy(F.spark_partition_id().alias("p")).count()
                .collect())
    by_p = {r["p"]: r["count"] for r in counts}
    return Skew([by_p.get(i, 0) for i in range(partitions)])


@dataclass(frozen=True)
class ExecutorMemory:
    heap_mb: int
    unified_mb: float        # execution + storage, shared
    storage_protected_mb: float
    user_mb: float


def executor_memory(heap_mb: int, memory_fraction: float = 0.6, storage_fraction: float = 0.5) -> ExecutorMemory:
    """Unified memory model: (heap - 300 MB) split between Spark's pool and user memory."""
    if heap_mb <= RESERVED_MB * 1.5:
        raise ValueError("executor heap must be at least 450 MB")
    usable = heap_mb - RESERVED_MB
    unified = usable * memory_fraction
    return ExecutorMemory(heap_mb, round(unified, 1), round(unified * storage_fraction, 1),
                          round(usable - unified, 1))
