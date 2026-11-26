"""Offline tests: data shape, BatchWriteItem retries and bulk operation polling, with botocore Stubber."""
import datetime as dt
import gzip
import json

import boto3
import pytest
from botocore.stub import Stubber

from bench import batchwrite, bulkput, data

ARN = "arn:aws:dynamodb:eu-west-1:111122223333:bulk-operation/01759414677739-041d6d92"


def ddb():
    return boto3.client("dynamodb", region_name="eu-west-1",
                        aws_access_key_id="test", aws_secret_access_key="test")


def test_items_are_about_1kb_and_deterministic():
    a = list(data.records(0, 50))
    b = list(data.records(0, 50))
    assert a == b
    sizes = [len(json.dumps(r["Item"], separators=(",", ":"))) for r in a]
    assert 900 <= min(sizes) and max(sizes) <= 1200
    assert {r["Item"]["category"]["S"] for r in data.records(0, 40)} == set(data.CATEGORIES)


def test_files_split_evenly_and_carry_conditions(tmp_path):
    paths = data.write_files(tmp_path, total=103, files=4, condition="attribute_not_exists(pk)")
    counts = [sum(1 for _ in gzip.open(p, "rt")) for p in paths]
    assert counts == [26, 26, 26, 25]
    first = json.loads(gzip.open(paths[0], "rt").readline())
    assert set(first) == {"Item", "ConditionExpression"}
    assert len(list(data.read_items(paths[3]))) == 25


def test_error_files_contain_the_planted_problems(tmp_path):
    good_bad, truncated = data.error_files(tmp_path)
    lines = gzip.open(good_bad, "rt").read().splitlines()
    assert len(lines) == 1000
    assert "pk" not in json.loads(lines[100])["Item"]
    assert json.loads(lines[400])["Item"]["pk"] == {"N": "400"}
    assert len(lines[700]) > 400_000
    tlines = gzip.open(truncated, "rt").read().splitlines()
    with pytest.raises(json.JSONDecodeError):
        json.loads(tlines[500])


def put_items(n):
    return [{"pk": {"S": f"order#{i}"}, "category": {"S": "cat-00"}} for i in range(n)]


def test_unprocessed_items_are_retried(monkeypatch):
    monkeypatch.setattr(batchwrite.time, "sleep", lambda s: None)
    client = ddb()
    items = put_items(3)
    with Stubber(client) as stub:
        stub.add_response("batch_write_item",
                          {"UnprocessedItems": {"t": [{"PutRequest": {"Item": items[2]}}]},
                           "ConsumedCapacity": [{"TableName": "t", "CapacityUnits": 2.0}]},
                          {"RequestItems": {"t": [{"PutRequest": {"Item": i}} for i in items]},
                           "ReturnConsumedCapacity": "TOTAL"})
        stub.add_response("batch_write_item",
                          {"UnprocessedItems": {}, "ConsumedCapacity": [{"TableName": "t", "CapacityUnits": 1.0}]},
                          {"RequestItems": {"t": [{"PutRequest": {"Item": items[2]}}]},
                           "ReturnConsumedCapacity": "TOTAL"})
        stats = batchwrite.Stats()
        batchwrite.write_batch("t", items, stats, ddb=client)
    assert (stats.items, stats.calls, stats.write_units, stats.unprocessed_retries) == (3, 2, 3.0, 1)


def test_throttling_error_is_retried_then_other_errors_raise(monkeypatch):
    monkeypatch.setattr(batchwrite.time, "sleep", lambda s: None)
    client = ddb()
    with Stubber(client) as stub:
        stub.add_client_error("batch_write_item", "ThrottlingException")
        stub.add_response("batch_write_item", {"UnprocessedItems": {}})
        stub.add_client_error("batch_write_item", "ValidationException")
        stats = batchwrite.Stats()
        batchwrite.write_batch("t", put_items(1), stats, ddb=client)
        assert stats.throttle_errors == 1 and stats.items == 1
        with pytest.raises(Exception, match="ValidationException"):
            batchwrite.write_batch("t", put_items(1), stats, ddb=client)


def test_backoff_is_bounded():
    assert all(0 <= batchwrite.backoff(a) <= 5.0 for a in range(30))


def test_chunks():
    assert [len(c) for c in batchwrite.chunks(range(60))] == [25, 25, 10]


def describe(status, **extra):
    return {"BulkOperationDescription": {"BulkOperationArn": ARN, "BulkOperationStatus": status, **extra}}


def test_wait_polls_until_terminal(monkeypatch):
    client = ddb()
    monkeypatch.setattr(bulkput, "client", lambda name: client)
    monkeypatch.setattr(bulkput.time, "sleep", lambda s: None)
    now = dt.datetime(2026, 11, 26, tzinfo=dt.timezone.utc)
    with Stubber(client) as stub:
        stub.add_response("describe_bulk_operation", describe("IN_PROGRESS"), {"BulkOperationArn": ARN})
        stub.add_response("describe_bulk_operation", describe(
            "COMPLETED", ProcessedItemCount=10, StartTime=now, EndTime=now,
            BulkOperationUsage=[{"TableName": "t", "Table": {"BulkPutBytes": 10240},
                                 "GlobalSecondaryIndexes": {"by-category": {"BulkPutBytes": 10240}}}]),
            {"BulkOperationArn": ARN})
        desc = bulkput.wait(ARN, poll=0)
    assert desc["BulkOperationStatus"] == "COMPLETED"
    assert [h["status"] for h in desc["PollHistory"]] == ["IN_PROGRESS", "COMPLETED"]
    assert bulkput.billed_bytes(desc) == {"table": 10240, "gsi:by-category": 10240}


def test_start_sends_the_documented_request(monkeypatch):
    client = ddb()
    monkeypatch.setattr(bulkput, "client", lambda name: client)
    monkeypatch.setattr(bulkput, "bucket", lambda: "b")
    with Stubber(client) as stub:
        stub.add_response("start_bulk_put_items", describe("IN_PROGRESS"), {
            "TableName": "t",
            "InputS3Configuration": {"S3Bucket": "b", "S3KeyPrefix": "full/", "InputFormat": "DYNAMODB_JSON",
                                     "InputCompressionType": "GZIP"},
            "OutputS3Configuration": {"S3Bucket": "b", "S3KeyPrefix": "reports/t/",
                                      "OutputType": ["ERROR", "CONDITION_CHECK_FAILURE"]},
            "PerformanceTier": "ACCELERATED", "ClientToken": "tok"})
        assert bulkput.start("t", "full/", "ACCELERATED", token="tok") == ARN
