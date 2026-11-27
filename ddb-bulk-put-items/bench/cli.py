"""Steps of the comparison. Run them in order with run.sh, or one at a time:

    python -m bench.cli setup | data | batchwrite | standard | rerun | accelerated
                       | import | errors | verify | teardown
    python -m bench.cli resume <result-name> <bulk-operation-arn>
"""
from __future__ import annotations

import datetime as dt
import gzip
import io
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor

from botocore.exceptions import ClientError

from . import batchwrite, bulkput, importtable
from .common import (DATA_DIR, GSI, REGION, RESULTS, TABLE_ACCEL, TABLE_BATCH, TABLE_ERRORS, TABLE_IMPORT,
                     TABLE_STANDARD, TABLES, TAG, Timer, account_id, bucket, client, key_schema,
                     save, wait_table)
from .data import error_files, write_files
from .traffic import AppTraffic

TOTAL = 1_000_000
FILES = 16
RERUN = 100_000


def log(msg: str) -> None:
    print(f"{dt.datetime.now(dt.timezone.utc):%H:%M:%S} {msg}", flush=True)


def setup(email: str | None = None) -> None:
    ddb = client("dynamodb")
    try:
        ddb.list_bulk_operations(MaxResults=1)
    except ClientError as err:
        sys.exit(f"bulk put items is not available here ({REGION}): {err}")
    log(f"bulk put items API answers in {REGION}")
    if email:
        budgets = client("budgets")
        try:
            budgets.create_budget(
                AccountId=account_id(),
                Budget={"BudgetName": "ddb-bulkput-blogtest", "BudgetLimit": {"Amount": "20", "Unit": "USD"},
                        "TimeUnit": "MONTHLY", "BudgetType": "COST"},
                NotificationsWithSubscribers=[{
                    "Notification": {"NotificationType": "ACTUAL", "ComparisonOperator": "GREATER_THAN",
                                     "Threshold": 50, "ThresholdType": "PERCENTAGE"},
                    "Subscribers": [{"SubscriptionType": "EMAIL", "Address": email}]}])
            log("budget alert created (USD 20, alert at 50%)")
        except ClientError as err:
            if err.response["Error"]["Code"] != "DuplicateRecordException":
                raise
    s3 = client("s3")
    try:
        s3.create_bucket(Bucket=bucket(), CreateBucketConfiguration={"LocationConstraint": REGION})
        s3.put_public_access_block(Bucket=bucket(), PublicAccessBlockConfiguration={
            "BlockPublicAcls": True, "IgnorePublicAcls": True, "BlockPublicPolicy": True, "RestrictPublicBuckets": True})
        s3.put_bucket_tagging(Bucket=bucket(), Tagging={"TagSet": [TAG]})
    except ClientError as err:
        if err.response["Error"]["Code"] != "BucketAlreadyOwnedByYou":
            raise
    log(f"bucket s3://{bucket()}")
    for name in TABLES:
        try:
            ddb.create_table(TableName=name, Tags=[TAG], **key_schema())
        except ClientError as err:
            if err.response["Error"]["Code"] != "ResourceInUseException":
                raise
    for name in TABLES:
        wait_table(name)
    log(f"tables active: {', '.join(TABLES)}")


def upload(prefix: str, paths) -> int:
    s3 = client("s3")
    total = 0
    for p in paths:
        s3.upload_file(str(p), bucket(), f"{prefix}{p.name}")
        total += p.stat().st_size
    return total


def data() -> None:
    with Timer() as t:
        full = write_files(DATA_DIR / "full", TOTAL, FILES)
        rerun = write_files(DATA_DIR / "rerun", RERUN, 4, condition="attribute_not_exists(pk)")
        errs = error_files(DATA_DIR / "errors")
    raw = sum(len(line) for p in full[:1] for line in gzip.open(p, "rt")) * len(full)
    sizes = {"full_gzip_bytes": upload("full/", full), "rerun_gzip_bytes": upload("rerun/", rerun),
             "errors_gzip_bytes": upload("errors/", errs), "full_raw_bytes_estimate": raw,
             "items": TOTAL, "files": len(full), "generate_and_upload_seconds": round(t.seconds, 1)}
    save("00-data", sizes)
    log(f"data uploaded: {sizes}")


def do_batchwrite() -> None:
    files = sorted((DATA_DIR / "full").glob("*.json.gz"))
    log(f"BatchWriteItem: {len(files)} files, 16 threads -> {TABLE_BATCH}")
    with Timer() as t:
        stats = batchwrite.load(TABLE_BATCH, files, workers=16)
    out = {"table": TABLE_BATCH, "seconds": round(t.seconds, 1), "items": stats.items, "calls": stats.calls,
           "write_units": stats.write_units, "unprocessed_retries": stats.unprocessed_retries,
           "throttle_errors": stats.throttle_errors, "items_per_second": round(stats.items / t.seconds)}
    save("01-batchwrite", out)
    log(f"BatchWriteItem done: {out}")


def run_bulk(name: str, table: str, prefix: str, tier: str, traffic: bool = False) -> dict:
    app = None
    windows = []
    if traffic:
        app = AppTraffic(table)
        app.start()
        log("app traffic: 60 s baseline before the import")
        time.sleep(60)
        windows.append(app.mark("during import").summary())
    started = time.time()
    arn = bulkput.start(table, prefix, tier)
    log(f"{name}: started {arn}")
    desc = bulkput.wait(arn, on_poll=lambda s: log(f"  {s['status']} items={s['processed_items']} "
                                                   f"bytes={s['processed_bytes']}/{s['total_bytes']}"))
    ended = time.time()
    if app:
        windows.append(app.mark("after import").summary())
        time.sleep(60)
        windows.append(app.stop().summary())
    out = {"table": table, "tier": tier, "status": desc["BulkOperationStatus"],
           "wall_seconds": round(ended - started, 1),
           "service_seconds": (desc["EndTime"] - desc["StartTime"]).total_seconds() if desc.get("EndTime") else None,
           "processed_items": desc.get("ProcessedItemCount"), "failed_items": desc.get("FailedItemCount"),
           "processed_input_bytes": desc.get("ProcessedInputBytes"), "total_input_bytes": desc.get("TotalInputBytes"),
           "billed_bytes": bulkput.billed_bytes(desc), "failure": desc.get("FailureCode"),
           "app_traffic": windows, "window": [started, ended], "describe": desc}
    save(name, out)
    log(f"{name}: {out['status']} in {out['wall_seconds']} s, billed {out['billed_bytes']}")
    if traffic:
        for w in windows:
            log(f"  app {w['label']}: put p50/p99 {w['put_ms']['p50']}/{w['put_ms']['p99']} ms, "
                f"get p50/p99 {w['get_ms']['p50']}/{w['get_ms']['p99']} ms, errors {w['errors']}")
    return out


def resume(name: str, arn: str) -> dict:
    """Pick up an operation whose waiting shell was closed (CloudShell times out after ~20 minutes idle).

    The operation keeps running in DynamoDB; this waits for it and saves the result like run_bulk.
    Wall time is not known here, so only the service's own start and end times are kept.
    """
    desc = bulkput.wait(arn, on_poll=lambda s: log(f"  {s['status']} items={s['processed_items']} "
                                                  f"bytes={s['processed_bytes']}/{s['total_bytes']}"))
    out = {"table": desc.get("TableName"), "tier": desc.get("PerformanceTier"), "status": desc["BulkOperationStatus"],
           "wall_seconds": None, "resumed": True,
           "service_seconds": (desc["EndTime"] - desc["StartTime"]).total_seconds() if desc.get("EndTime") else None,
           "processed_items": desc.get("ProcessedItemCount"), "failed_items": desc.get("FailedItemCount"),
           "processed_input_bytes": desc.get("ProcessedInputBytes"), "total_input_bytes": desc.get("TotalInputBytes"),
           "billed_bytes": bulkput.billed_bytes(desc), "failure": desc.get("FailureCode"),
           "window": [desc["StartTime"].timestamp(), desc["EndTime"].timestamp()] if desc.get("EndTime") else None,
           "describe": desc}
    save(name, out)
    log(f"{name}: {out['status']} in {out['service_seconds']} s (service time), billed {out['billed_bytes']}")
    return out


def consumed_writes(table: str, start: float, end: float) -> float:
    """Sum of ConsumedWriteCapacityUnits for the table between start and end (1-minute data)."""
    cw = client("cloudwatch")
    resp = cw.get_metric_statistics(
        Namespace="AWS/DynamoDB", MetricName="ConsumedWriteCapacityUnits",
        Dimensions=[{"Name": "TableName", "Value": table}],
        StartTime=dt.datetime.fromtimestamp(start - 60, dt.timezone.utc),
        EndTime=dt.datetime.fromtimestamp(end + 60, dt.timezone.utc), Period=60, Statistics=["Sum"])
    return sum(p["Sum"] for p in resp["Datapoints"])


def writes_last_day(table: str, index: str | None = None) -> float:
    """ConsumedWriteCapacityUnits summed over 24 hours, for the table or one of its GSIs.

    Bulk put items does not consume the table's write capacity, so this separates what
    BatchWriteItem and the application thread consumed from what the bulk loads wrote.
    """
    dims = [{"Name": "TableName", "Value": table}]
    if index:
        dims.append({"Name": "GlobalSecondaryIndexName", "Value": index})
    end = dt.datetime.now(dt.timezone.utc)
    resp = client("cloudwatch").get_metric_statistics(
        Namespace="AWS/DynamoDB", MetricName="ConsumedWriteCapacityUnits", Dimensions=dims,
        StartTime=end - dt.timedelta(hours=24), EndTime=end, Period=3600, Statistics=["Sum"])
    return sum(p["Sum"] for p in resp["Datapoints"])


def count(table: str, segments: int = 8) -> int:
    ddb = client("dynamodb")

    def seg(i: int) -> int:
        n, kwargs = 0, {"TableName": table, "Select": "COUNT", "Segment": i, "TotalSegments": segments}
        while True:
            page = ddb.scan(**kwargs)
            n += page["Count"]
            if "LastEvaluatedKey" not in page:
                return n
            kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]

    with ThreadPoolExecutor(segments) as pool:
        return sum(pool.map(seg, range(segments)))


def reports(table: str) -> dict:
    """What the S3 report contains: object names, line counts and the first record of each."""
    s3 = client("s3")
    found = {}
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket(), Prefix=f"reports/{table}/"):
        for obj in page.get("Contents", []):
            whole = obj["Size"] < 5_000_000
            kwargs = {} if whole else {"Range": "bytes=0-262143"}
            body = s3.get_object(Bucket=bucket(), Key=obj["Key"], **kwargs)["Body"].read()
            if body[:2] == b"\x1f\x8b":
                try:
                    body = gzip.GzipFile(fileobj=io.BytesIO(body)).read()
                except EOFError:  # a ranged read of a large gzip object ends mid-stream
                    body = gzip.GzipFile(fileobj=io.BytesIO(body)).read1(10**7)
            text = body.decode("utf-8", errors="replace")
            lines = [ln for ln in text.splitlines() if ln.strip()]
            found[obj["Key"]] = {"bytes": obj["Size"], "lines": len(lines) if whole else None,
                                 "first": lines[0][:600] if lines else ""}
    return found


def verify() -> None:
    out = {}
    for name in ("02-standard", "04-accelerated"):
        try:
            r = json.loads((RESULTS / f"{name}.json").read_text())
            out[f"{name}_table_wcu_during_import"] = consumed_writes(r["table"], *r["window"])
        except FileNotFoundError:
            pass
    for table in (TABLE_BATCH, TABLE_STANDARD, TABLE_ACCEL, TABLE_IMPORT):
        try:
            out[f"count_{table}"] = count(table)
            out[f"wcu_24h_{table}"] = writes_last_day(table)
            out[f"wcu_24h_{table}_gsi"] = writes_last_day(table, GSI)
        except ClientError as err:
            out[f"count_{table}"] = err.response["Error"]["Code"]
    out["reports_rerun"] = reports(TABLE_STANDARD)
    out["reports_errors"] = reports(TABLE_ERRORS)
    save("07-verify", out)
    log(json.dumps({k: v for k, v in out.items() if not k.startswith("reports")}, indent=1))


def teardown() -> None:
    ddb, s3 = client("dynamodb"), client("s3")
    for name in TABLES + [TABLE_IMPORT]:
        try:
            ddb.delete_table(TableName=name)
            log(f"deleting table {name}")
        except ClientError as err:
            if err.response["Error"]["Code"] != "ResourceNotFoundException":
                raise
    try:
        paginator = s3.get_paginator("list_object_versions")
        for page in paginator.paginate(Bucket=bucket()):
            objs = [{"Key": o["Key"], "VersionId": o["VersionId"]}
                    for o in page.get("Versions", []) + page.get("DeleteMarkers", [])]
            if objs:
                s3.delete_objects(Bucket=bucket(), Delete={"Objects": objs})
        s3.delete_bucket(Bucket=bucket())
        log(f"deleted bucket {bucket()}")
    except ClientError as err:
        if err.response["Error"]["Code"] != "NoSuchBucket":
            raise
    try:
        client("budgets").delete_budget(AccountId=account_id(), BudgetName="ddb-bulkput-blogtest")
    except ClientError:
        pass
    for name in TABLES + [TABLE_IMPORT]:
        try:
            ddb.get_waiter("table_not_exists").wait(TableName=name, WaiterConfig={"Delay": 5, "MaxAttempts": 60})
        except Exception:  # noqa: BLE001 - report below
            pass
    left = [t for t in ddb.list_tables()["TableNames"] if t.startswith("bulkput-blogtest")]
    buckets = [b["Name"] for b in s3.list_buckets()["Buckets"] if b["Name"] == bucket()]
    log(f"left over: tables={left} buckets={buckets}")


def main(argv: list[str]) -> None:
    step = argv[1] if len(argv) > 1 else ""
    steps = {
        "setup": lambda: setup(argv[2] if len(argv) > 2 else None),
        "data": data,
        "batchwrite": do_batchwrite,
        "standard": lambda: run_bulk("02-standard", TABLE_STANDARD, "full/", "STANDARD", traffic=True),
        "rerun": lambda: run_bulk("03-rerun-conditional", TABLE_STANDARD, "rerun/", "STANDARD"),
        "accelerated": lambda: run_bulk("04-accelerated", TABLE_ACCEL, "full/", "ACCELERATED"),
        "import": lambda: save("05-import", importtable.run(TABLE_IMPORT, "full/")),
        "errors": lambda: run_bulk("06-errors", TABLE_ERRORS, "errors/", "STANDARD"),
        "verify": verify,
        "resume": lambda: resume(argv[2], argv[3]),
        "teardown": teardown,
    }
    if step not in steps:
        sys.exit(__doc__)
    steps[step]()


if __name__ == "__main__":
    main(sys.argv)
