# spark-internals-lab

Companion code for the dataa.dev article *Inside a Spark Job: Stages, Shuffles, AQE and Memory, and How to Read Them* (9 November 2025).

`spark_lab.py` has small helpers for looking inside a Spark 4.0 job, and the tests turn the internals described in the article into checks that run on a laptop (`local[2]`):

| Helper | What it shows |
| :--- | :--- |
| `physical_plan(df)` | The executed physical plan of this exact DataFrame after Adaptive Query Execution has finalised it |
| `count_exchanges(plan)` | Shuffle boundaries (stages) in a plan; broadcast exchanges are not counted |
| `join_strategy(plan)` | Broadcast hash, sort-merge, shuffled hash or nested-loop join |
| `partition_skew(df, key, n)` | Rows per partition after hash partitioning, and the max/median ratio |
| `executor_memory(heap_mb)` | The unified memory model: 300 MB reserved, `spark.memory.fraction` for execution and storage, the rest for user memory |

## Tests

```bash
pip install pyspark==4.0.1 pytest==8.4.2      # needs Java 17 or 21
python -m pytest -q
```

6 tests, run with Python 3.12, PySpark 4.0.1 and OpenJDK 21: transformations are lazy until an action; `groupBy` adds a shuffle and a filter does not; a small dimension is broadcast unless the threshold is disabled (then sort-merge); AQE coalesces 200 shuffle partitions, and without AQE all 200 stay; a hot key produces a high skew ratio; the memory arithmetic.

The helpers use the classic PySpark API's access to the JVM query execution. With Spark Connect, read the same information from `df.explain(mode="formatted")` or the Spark UI.
