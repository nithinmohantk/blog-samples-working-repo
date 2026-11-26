"""Names, clients and small helpers shared by every step."""
from __future__ import annotations

import json
import os
import time
from functools import lru_cache
from pathlib import Path

import boto3
from botocore.config import Config

REGION = os.environ.get("AWS_REGION", "eu-west-1")
TAG = {"Key": "project", "Value": "ddb-bulkput-blogtest"}
RESULTS = Path(__file__).resolve().parent.parent / "results"
DATA_DIR = Path(os.environ.get("DATA_DIR", "/tmp/ddb-bulkput-data"))

# Adaptive retries: botocore backs off on throttling instead of failing the call.
CONFIG = Config(region_name=REGION, retries={"mode": "adaptive", "max_attempts": 10},
                max_pool_connections=64, connect_timeout=5, read_timeout=30)

TABLE_BATCH = "bulkput-blogtest-batchwrite"   # A: BatchWriteItem loop
TABLE_STANDARD = "bulkput-blogtest-standard"  # B: bulk put items, Standard tier
TABLE_ACCEL = "bulkput-blogtest-accelerated"  # C: bulk put items, Accelerated tier
TABLE_IMPORT = "bulkput-blogtest-import"      # D: created by ImportTable
TABLE_ERRORS = "bulkput-blogtest-errors"      # E: small table for the bad-records run
TABLES = [TABLE_BATCH, TABLE_STANDARD, TABLE_ACCEL, TABLE_ERRORS]
GSI = "by-category"


@lru_cache
def client(service: str):
    return boto3.client(service, config=CONFIG)


@lru_cache
def account_id() -> str:
    return client("sts").get_caller_identity()["Account"]


def bucket() -> str:
    return f"ddb-bulkput-blogtest-{account_id()}-{REGION}"


def key_schema() -> dict:
    """Same schema for every table, so the loads are comparable."""
    return {
        "AttributeDefinitions": [
            {"AttributeName": "pk", "AttributeType": "S"},
            {"AttributeName": "category", "AttributeType": "S"},
        ],
        "KeySchema": [{"AttributeName": "pk", "KeyType": "HASH"}],
        "BillingMode": "PAY_PER_REQUEST",
        "GlobalSecondaryIndexes": [{
            "IndexName": GSI,
            "KeySchema": [{"AttributeName": "category", "KeyType": "HASH"},
                          {"AttributeName": "pk", "KeyType": "RANGE"}],
            "Projection": {"ProjectionType": "KEYS_ONLY"},
        }],
    }


def save(name: str, data: dict) -> Path:
    RESULTS.mkdir(exist_ok=True)
    path = RESULTS / f"{name}.json"
    path.write_text(json.dumps(data, indent=2, default=str))
    return path


def wait_table(name: str, timeout: float = 600) -> None:
    client("dynamodb").get_waiter("table_exists").wait(
        TableName=name, WaiterConfig={"Delay": 5, "MaxAttempts": int(timeout / 5)})


def percentile(values: list[float], p: float) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    k = max(0, min(len(ordered) - 1, round(p / 100 * (len(ordered) - 1))))
    return ordered[k]


class Timer:
    def __enter__(self):
        self.start = time.monotonic()
        return self

    def __exit__(self, *exc):
        self.seconds = time.monotonic() - self.start
