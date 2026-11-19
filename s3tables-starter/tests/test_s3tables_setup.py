"""Tests run against botocore's Stubber, which validates every request against
the s3tables service model shipped with the pinned botocore version."""

from datetime import datetime, timezone

import boto3
import pytest
from botocore.exceptions import ParamValidationError
from botocore.stub import ANY, Stubber

import s3tables_setup as s
from cost_model import Workload, monthly_cost

ARN = "arn:aws:s3tables:eu-west-1:111122223333:bucket/finance-lakehouse"
NOW = datetime(2026, 2, 16, tzinfo=timezone.utc)

PAYMENTS = s.TableSpec(
    namespace="finance",
    name="payments",
    columns=[
        s.Column(1, "payment_id", "string", required=True),
        s.Column(2, "account_id", "string", required=True),
        s.Column(3, "amount", "decimal(18,2)", required=True),
        s.Column(6, "created_at", "timestamptz", required=True),
    ],
    partition=[("created_at", "day")],
    sort=["account_id"],
)


@pytest.fixture
def client():
    c = boto3.client("s3tables", region_name="eu-west-1",
                     aws_access_key_id="x", aws_secret_access_key="x")
    with Stubber(c) as stub:
        c.stub = stub
        yield c
        if not getattr(c, "allow_pending", False):
            stub.assert_no_pending_responses()


def test_create_table_request_matches_service_model(client):
    kwargs = PAYMENTS.create_table_kwargs(ARN)
    assert kwargs["metadata"]["iceberg"]["partitionSpec"]["fields"] == [
        {"sourceId": 6, "transform": "day", "name": "created_at_day"}]
    assert kwargs["metadata"]["iceberg"]["writeOrder"]["fields"][0]["sourceId"] == 2
    client.stub.add_response("create_table", {"tableARN": ARN + "/table/abc", "versionToken": "v1"}, kwargs)
    assert s.ensure_table(client, ARN, PAYMENTS).endswith("/table/abc")


def test_existing_table_is_returned(client):
    client.stub.add_client_error("create_table", "ConflictException", http_status_code=409)
    client.stub.add_response("get_table", {
        "name": "payments", "type": "customer", "tableARN": ARN + "/table/old", "namespace": ["finance"],
        "versionToken": "v", "warehouseLocation": "s3://x", "createdAt": NOW, "createdBy": "111122223333",
        "modifiedAt": NOW, "modifiedBy": "111122223333", "ownerAccountId": "111122223333", "format": "ICEBERG"},
        {"tableBucketARN": ARN, "namespace": "finance", "name": "payments"})
    assert s.ensure_table(client, ARN, PAYMENTS).endswith("/table/old")


def test_existing_bucket_is_found_by_listing(client):
    client.stub.add_client_error("create_table_bucket", "ConflictException", http_status_code=409)
    client.stub.add_response("list_table_buckets", {"tableBuckets": [
        {"arn": ARN, "name": "finance-lakehouse", "ownerAccountId": "111122223333", "createdAt": NOW}]},
        {"prefix": "finance-lakehouse"})
    assert s.ensure_table_bucket(client, "finance-lakehouse") == ARN


def test_bucket_with_kms_key(client):
    key = "arn:aws:kms:eu-west-1:111122223333:key/1234"
    client.stub.add_response("create_table_bucket", {"arn": ARN}, {
        "name": "finance-lakehouse",
        "encryptionConfiguration": {"sseAlgorithm": "aws:kms", "kmsKeyArn": key}})
    assert s.ensure_table_bucket(client, "finance-lakehouse", key) == ARN


def test_other_errors_are_raised(client):
    client.stub.add_client_error("create_namespace", "AccessDeniedException", http_status_code=403)
    with pytest.raises(Exception, match="AccessDenied"):
        s.ensure_namespace(client, ARN, "finance")


def test_maintenance_requests_match_service_model(client):
    for _ in range(2):
        client.stub.add_response("put_table_maintenance_configuration", {}, {
            "tableBucketARN": ARN, "namespace": "finance", "name": "payments",
            "type": ANY, "value": ANY})
    s.configure_maintenance(client, ARN, PAYMENTS, target_file_mb=256, strategy="sort")
    client.stub.add_response("put_table_bucket_maintenance_configuration", {}, {
        "tableBucketARN": ARN, "type": "icebergUnreferencedFileRemoval",
        "value": {"status": "enabled", "settings": {"icebergUnreferencedFileRemoval": {
            "unreferencedDays": 3, "nonCurrentDays": 10}}}})
    s.configure_unreferenced_file_removal(client, ARN)


@pytest.mark.parametrize("kwargs,msg", [
    ({"target_file_mb": 1024}, "between 64 and 512"),
    ({"strategy": "hilbert"}, "strategy must be"),
])
def test_maintenance_validation(client, kwargs, msg):
    with pytest.raises(ValueError, match=msg):
        s.configure_maintenance(client, ARN, PAYMENTS, **kwargs)


def test_z_order_needs_sort_order(client):
    unsorted = s.TableSpec("finance", "fx_rates", [s.Column(1, "pair", "string")])
    with pytest.raises(ValueError, match="needs a sort order"):
        s.configure_maintenance(client, ARN, unsorted, strategy="z-order")


def test_invalid_parameters_are_rejected_by_the_model(client):
    # create_table has no maintenanceConfig field; maintenance is a separate API call.
    client.stub.add_response("create_table", {"tableARN": ARN + "/table/x", "versionToken": "v"})
    with pytest.raises(ParamValidationError, match="maintenanceConfig"):
        client.create_table(tableBucketARN=ARN, namespace="finance", name="t", format="ICEBERG",
                            maintenanceConfig={})
    client.allow_pending = True


def test_upper_case_names_rejected():
    with pytest.raises(ValueError, match="lower-case"):
        s.TableSpec("Finance", "payments", [s.Column(1, "id", "string")])


def test_snapshot_management_blockers():
    props = {"history.expire.max-snapshot-age-ms": "86400000", "write.format.default": "parquet"}
    refs = {"main": {"type": "branch", "snapshot-id": 1},
            "eoy-2025": {"type": "tag", "snapshot-id": 2}}
    assert s.snapshot_management_blockers(props, refs) == [
        "table property history.expire.max-snapshot-age-ms is set", "tag 'eoy-2025' exists"]
    assert s.snapshot_management_blockers({}, {"main": {"type": "branch"}}) == []


def test_pyiceberg_properties():
    p = s.pyiceberg_properties("eu-west-1", "111122223333", "finance-lakehouse")
    assert p["warehouse"] == ARN
    assert p["uri"] == "https://s3tables.eu-west-1.amazonaws.com/iceberg"
    assert p["rest.signing-name"] == "s3tables"


def test_cost_model_reproduces_aws_example():
    # AWS pricing page example: 1 TB table, 100 MB objects, US West (Oregon).
    cost = monthly_cost(Workload(storage_gb=1024, objects=10_486, puts=30_000, gets=500_000,
                                 compaction_objects=30_000, compaction_gb=146.48))
    assert cost == {"storage": 27.14, "put_requests": 0.15, "get_requests": 0.2,
                    "monitoring": 0.26, "compaction_objects": 0.06, "compaction_data": 0.73,
                    "total": 28.54}
