"""Create Amazon S3 Tables resources idempotently and set table maintenance.

The functions take a boto3 ``s3tables`` client so they can be tested with
botocore's Stubber and reused from scripts, Lambda functions or CI jobs.
Defaults follow the S3 Tables documentation as of February 2026:
compaction target file size 64-512 MB (default 512), snapshot retention
default 1 snapshot / 120 hours, unreferenced file removal 3 + 10 days.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from botocore.exceptions import ClientError

log = logging.getLogger(__name__)

COMPACTION_STRATEGIES = {"auto", "binpack", "sort", "z-order"}
RISKY_PROPERTIES = (
    "history.expire.max-snapshot-age-ms",
    "history.expire.min-snapshots-to-keep",
)


@dataclass(frozen=True)
class Column:
    id: int
    name: str
    type: str  # Iceberg type string, e.g. "long", "decimal(18,2)", "timestamptz"
    required: bool = False


@dataclass(frozen=True)
class TableSpec:
    namespace: str
    name: str
    columns: list[Column]
    partition: list[tuple[str, str]] = field(default_factory=list)  # (column, transform)
    sort: list[str] = field(default_factory=list)                  # columns, ascending
    storage_class: str = "STANDARD"

    def __post_init__(self) -> None:
        for label in (self.namespace, self.name, *(c.name for c in self.columns)):
            if label != label.lower():
                # Upper-case names are invisible to Glue Data Catalog and Athena.
                raise ValueError(f"use lower-case names for S3 Tables: {label!r}")
        ids = [c.id for c in self.columns]
        if len(ids) != len(set(ids)):
            raise ValueError("column ids must be unique")

    def _id(self, column: str) -> int:
        for c in self.columns:
            if c.name == column:
                return c.id
        raise ValueError(f"unknown column {column!r}")

    def create_table_kwargs(self, bucket_arn: str) -> dict[str, Any]:
        iceberg: dict[str, Any] = {
            "schema": {"fields": [
                {"id": c.id, "name": c.name, "type": c.type, "required": c.required}
                for c in self.columns]},
        }
        if self.partition:
            iceberg["partitionSpec"] = {"fields": [
                {"sourceId": self._id(col), "transform": t, "name": f"{col}_{t.split('[')[0]}"}
                for col, t in self.partition]}
        if self.sort:
            iceberg["writeOrder"] = {"orderId": 1, "fields": [
                {"sourceId": self._id(col), "transform": "identity",
                 "direction": "asc", "nullOrder": "nulls-last"} for col in self.sort]}
        return {
            "tableBucketARN": bucket_arn,
            "namespace": self.namespace,
            "name": self.name,
            "format": "ICEBERG",
            "metadata": {"iceberg": iceberg},
            "storageClassConfiguration": {"storageClass": self.storage_class},
        }


def _is(err: ClientError, code: str) -> bool:
    return err.response.get("Error", {}).get("Code") == code


def ensure_table_bucket(client: Any, name: str, kms_key_arn: str | None = None) -> str:
    """Create the table bucket, or return the ARN of the existing one."""
    kwargs: dict[str, Any] = {"name": name}
    if kms_key_arn:
        kwargs["encryptionConfiguration"] = {"sseAlgorithm": "aws:kms", "kmsKeyArn": kms_key_arn}
    try:
        return client.create_table_bucket(**kwargs)["arn"]
    except ClientError as err:
        if not _is(err, "ConflictException"):
            raise
    for page in client.get_paginator("list_table_buckets").paginate(prefix=name):
        for bucket in page["tableBuckets"]:
            if bucket["name"] == name:
                return bucket["arn"]
    raise RuntimeError(f"table bucket {name} exists but is not visible to this caller")


def ensure_namespace(client: Any, bucket_arn: str, namespace: str) -> None:
    try:
        client.create_namespace(tableBucketARN=bucket_arn, namespace=[namespace])
    except ClientError as err:
        if not _is(err, "ConflictException"):
            raise
        log.info("namespace %s already exists", namespace)


def ensure_table(client: Any, bucket_arn: str, spec: TableSpec) -> str:
    """Create the table with its schema, partitioning and sort order; return its ARN."""
    try:
        return client.create_table(**spec.create_table_kwargs(bucket_arn))["tableARN"]
    except ClientError as err:
        if not _is(err, "ConflictException"):
            raise
    return client.get_table(tableBucketARN=bucket_arn, namespace=spec.namespace,
                            name=spec.name)["tableARN"]


def configure_maintenance(client: Any, bucket_arn: str, spec: TableSpec, *,
                          target_file_mb: int = 512, strategy: str = "auto",
                          min_snapshots: int = 1, max_snapshot_age_hours: int = 120) -> None:
    """Set compaction and snapshot management for one table."""
    if not 64 <= target_file_mb <= 512:
        raise ValueError("targetFileSizeMB must be between 64 and 512")
    if strategy not in COMPACTION_STRATEGIES:
        raise ValueError(f"strategy must be one of {sorted(COMPACTION_STRATEGIES)}")
    if strategy in {"sort", "z-order"} and not spec.sort:
        raise ValueError(f"{strategy} compaction needs a sort order on the table")
    where = {"tableBucketARN": bucket_arn, "namespace": spec.namespace, "name": spec.name}
    client.put_table_maintenance_configuration(
        **where, type="icebergCompaction",
        value={"status": "enabled", "settings": {"icebergCompaction": {
            "targetFileSizeMB": target_file_mb, "strategy": strategy}}})
    client.put_table_maintenance_configuration(
        **where, type="icebergSnapshotManagement",
        value={"status": "enabled", "settings": {"icebergSnapshotManagement": {
            "minSnapshotsToKeep": min_snapshots,
            "maxSnapshotAgeHours": max_snapshot_age_hours}}})


def configure_unreferenced_file_removal(client: Any, bucket_arn: str, *,
                                        unreferenced_days: int = 3,
                                        noncurrent_days: int = 10) -> None:
    """Bucket-level setting. Noncurrent files are deleted permanently after noncurrent_days."""
    client.put_table_bucket_maintenance_configuration(
        tableBucketARN=bucket_arn, type="icebergUnreferencedFileRemoval",
        value={"status": "enabled", "settings": {"icebergUnreferencedFileRemoval": {
            "unreferencedDays": unreferenced_days, "nonCurrentDays": noncurrent_days}}})


def snapshot_management_blockers(properties: dict[str, str], refs: dict[str, Any]) -> list[str]:
    """Return reasons S3 Tables snapshot management would fail for a table.

    ``properties`` and ``refs`` come from the table's metadata.json. Any tag or
    branch other than ``main``, or either history.expire property, makes the
    managed snapshot expiry fail for the whole table.
    """
    problems = [f"table property {p} is set" for p in RISKY_PROPERTIES if p in properties]
    problems += [f"{ref['type']} {name!r} exists" for name, ref in refs.items() if name != "main"]
    return problems


def pyiceberg_properties(region: str, account_id: str, bucket: str) -> dict[str, str]:
    """Catalog properties for PyIceberg against the S3 Tables Iceberg REST endpoint."""
    return {
        "type": "rest",
        "warehouse": f"arn:aws:s3tables:{region}:{account_id}:bucket/{bucket}",
        "uri": f"https://s3tables.{region}.amazonaws.com/iceberg",
        "rest.sigv4-enabled": "true",
        "rest.signing-name": "s3tables",
        "rest.signing-region": region,
    }


if __name__ == "__main__":
    import boto3

    logging.basicConfig(level=logging.INFO)
    s3tables = boto3.client("s3tables")
    payments = TableSpec(
        namespace="finance",
        name="payments",
        columns=[
            Column(1, "payment_id", "string", required=True),
            Column(2, "account_id", "string", required=True),
            Column(3, "amount", "decimal(18,2)", required=True),
            Column(4, "currency", "string"),
            Column(5, "status", "string"),
            Column(6, "created_at", "timestamptz", required=True),
        ],
        partition=[("created_at", "day")],
        sort=["account_id"],
    )
    arn = ensure_table_bucket(s3tables, "finance-lakehouse")
    ensure_namespace(s3tables, arn, payments.namespace)
    print(ensure_table(s3tables, arn, payments))
    configure_maintenance(s3tables, arn, payments, target_file_mb=256)
    configure_unreferenced_file_removal(s3tables, arn)
