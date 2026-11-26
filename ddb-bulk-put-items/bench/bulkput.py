"""Start a bulk put items operation, wait for it, and keep what describe-bulk-operation says."""
from __future__ import annotations

import time
import uuid

from .common import bucket, client

TERMINAL = {"COMPLETED", "COMPLETED_WITH_ERRORS", "CANCELLED", "FAILED"}


def start(table: str, prefix: str, tier: str = "STANDARD", report_prefix: str | None = None,
          max_wru: int | None = None, token: str | None = None) -> str:
    params = {
        "TableName": table,
        "InputS3Configuration": {"S3Bucket": bucket(), "S3KeyPrefix": prefix,
                                 "InputFormat": "DYNAMODB_JSON", "InputCompressionType": "GZIP"},
        "OutputS3Configuration": {"S3Bucket": bucket(), "S3KeyPrefix": report_prefix or f"reports/{table}/",
                                  "OutputType": ["ERROR", "CONDITION_CHECK_FAILURE"]},
        "PerformanceTier": tier,
        # Idempotent start: a retried call with the same token returns the same operation.
        "ClientToken": token or f"{table}-{uuid.uuid4()}",
    }
    if max_wru:
        params["MaxWriteRequestUnits"] = max_wru
    resp = client("dynamodb").start_bulk_put_items(**params)
    return resp["BulkOperationDescription"]["BulkOperationArn"]


def wait(arn: str, poll: float = 15.0, timeout: float = 4 * 3600, on_poll=None) -> dict:
    """Poll until a terminal state. Counters are periodic snapshots, not live values."""
    ddb = client("dynamodb")
    deadline = time.monotonic() + timeout
    history = []
    while True:
        desc = ddb.describe_bulk_operation(BulkOperationArn=arn)["BulkOperationDescription"]
        snap = {"t": time.time(), "status": desc["BulkOperationStatus"],
                "processed_items": desc.get("ProcessedItemCount"),
                "processed_bytes": desc.get("ProcessedInputBytes"),
                "total_bytes": desc.get("TotalInputBytes")}
        history.append(snap)
        if on_poll:
            on_poll(snap)
        if desc["BulkOperationStatus"] in TERMINAL:
            desc["PollHistory"] = history
            return desc
        if time.monotonic() > deadline:
            raise TimeoutError(f"{arn} still {desc['BulkOperationStatus']} after {timeout} s")
        time.sleep(poll)


def billed_bytes(desc: dict) -> dict:
    """Bytes DynamoDB metered for the table and each index (the basis of the per-GB charge)."""
    out = {}
    for usage in desc.get("BulkOperationUsage", []):
        out["table"] = usage.get("Table", {}).get("BulkPutBytes", 0)
        for name, gsi in (usage.get("GlobalSecondaryIndexes") or {}).items():
            out[f"gsi:{name}"] = gsi.get("BulkPutBytes", 0)
    return out
