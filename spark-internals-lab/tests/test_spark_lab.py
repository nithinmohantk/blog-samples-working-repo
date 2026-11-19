import pytest
from pyspark.sql import SparkSession, functions as F

import spark_lab as lab


@pytest.fixture(scope="module")
def spark():
    s = (SparkSession.builder.master("local[2]").appName("spark-internals-lab")
         .config("spark.ui.enabled", "false")
         .config("spark.sql.shuffle.partitions", "200")
         .getOrCreate())
    s.sparkContext.setLogLevel("ERROR")
    yield s
    s.stop()


@pytest.fixture(scope="module")
def frames(spark):
    orders = spark.range(0, 200_000).select(
        F.col("id").alias("order_id"),
        (F.col("id") % 1000).alias("customer_id"),
        (F.col("id") % 97).cast("double").alias("amount"))
    customers = spark.range(0, 1000).select(F.col("id").alias("customer_id"),
                                             (F.col("id") % 5).alias("segment"))
    return orders, customers


def test_transformations_are_lazy_until_an_action(spark, frames):
    orders, _ = frames
    tracker = spark.sparkContext.statusTracker()
    before = set(tracker.getJobIdsForGroup())
    plan = orders.filter(F.col("amount") > 50).groupBy("customer_id").agg(F.sum("amount"))
    assert set(tracker.getJobIdsForGroup()) == before          # nothing ran yet
    plan.count()
    assert set(tracker.getJobIdsForGroup()) - before            # the action ran jobs


def test_groupby_introduces_a_shuffle(frames):
    orders, _ = frames
    narrow = orders.filter(F.col("amount") > 50).select("order_id")
    wide = orders.groupBy("customer_id").agg(F.sum("amount").alias("total"))
    assert lab.count_exchanges(lab.physical_plan(narrow)) == 0
    assert lab.count_exchanges(lab.physical_plan(wide)) >= 1


def test_small_dimension_is_broadcast_unless_disabled(spark, frames):
    orders, customers = frames
    joined = orders.join(customers, "customer_id")
    assert lab.join_strategy(lab.physical_plan(joined)) == "BroadcastHashJoin"
    spark.conf.set("spark.sql.autoBroadcastJoinThreshold", "-1")
    spark.conf.set("spark.sql.adaptive.enabled", "false")
    try:
        assert lab.join_strategy(lab.physical_plan(orders.join(customers, "customer_id"))) == "SortMergeJoin"
    finally:
        spark.conf.unset("spark.sql.autoBroadcastJoinThreshold")
        spark.conf.unset("spark.sql.adaptive.enabled")


def test_aqe_coalesces_small_shuffle_partitions(spark, frames):
    orders, _ = frames
    agg = orders.groupBy("customer_id").agg(F.sum("amount"))
    spark.conf.set("spark.sql.adaptive.enabled", "true")
    plan_on = lab.physical_plan(agg)
    assert "AQEShuffleRead" in plan_on and "coalesced" in plan_on
    spark.conf.set("spark.sql.adaptive.enabled", "false")
    try:
        plan_off = lab.physical_plan(orders.groupBy("customer_id").agg(F.sum("amount")))
        assert "AQEShuffleRead" not in plan_off and ", 200)" in plan_off   # all 200 partitions kept
    finally:
        spark.conf.unset("spark.sql.adaptive.enabled")


def test_partition_skew_detects_a_hot_key(spark):
    even = spark.range(0, 100_000).select((F.col("id") % 100).alias("k"))
    hot = spark.range(0, 100_000).select(F.when(F.col("id") % 10 < 8, F.lit(0))
                                         .otherwise(F.col("id") % 100).alias("k"))
    assert lab.partition_skew(even, "k", 8).ratio < 1.5
    assert lab.partition_skew(hot, "k", 8).ratio > 4


def test_executor_memory_model():
    m = lab.executor_memory(16 * 1024)                 # 16 GiB heap
    assert m.unified_mb == pytest.approx((16384 - 300) * 0.6, abs=0.1)
    assert m.storage_protected_mb == pytest.approx(m.unified_mb / 2, abs=0.1)
    assert m.user_mb == pytest.approx((16384 - 300) * 0.4, abs=0.1)
    with pytest.raises(ValueError):
        lab.executor_memory(400)
