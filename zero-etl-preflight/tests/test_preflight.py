"""AWS calls go through botocore's Stubber, which validates them against the RDS
and Redshift API models in the pinned botocore release. The SQL test runs
against a local PostgreSQL if PG_DSN is set."""

import json
import os
from datetime import datetime, timezone

import boto3
import pytest
from botocore.stub import Stubber

import preflight as p

SRC = "arn:aws:rds:eu-west-1:111122223333:cluster:orders-prod"
NS = "arn:aws:redshift-serverless:eu-west-1:111122223333:namespace/7b1f2c3d-aaaa-bbbb-cccc-111122223333"
NOW = datetime(2026, 4, 27, tzinfo=timezone.utc)


def client(name):
    return boto3.client(name, region_name="eu-west-1", aws_access_key_id="x", aws_secret_access_key="x")


def test_parameter_check_mysql():
    good = dict(p.REQUIRED["aurora-mysql"])
    assert p.check_parameters("aurora-mysql", good) == []
    bad = {**good, "binlog_format": "MIXED", "binlog_transaction_compression": "ON"}
    bad.pop("aurora_enhanced_binlog")
    problems = p.check_parameters("aurora-mysql", bad)
    assert "aurora_enhanced_binlog is None, must be '1'" in problems
    assert "binlog_format is 'MIXED', must be 'ROW'" in problems
    assert "binlog_transaction_compression must not be 'ON'" in problems


def test_parameter_check_postgresql_and_paging():
    rds = client("rds")
    with Stubber(rds) as stub:
        stub.add_response("describe_db_cluster_parameters", {"Parameters": [
            {"ParameterName": "rds.logical_replication", "ParameterValue": "1"},
            {"ParameterName": "aurora.enhanced_logical_replication", "ParameterValue": "1"}],
            "Marker": "m1"}, {"DBClusterParameterGroupName": "orders-zero-etl"})
        stub.add_response("describe_db_cluster_parameters", {"Parameters": [
            {"ParameterName": "aurora.logical_replication_backup", "ParameterValue": "1"},
            {"ParameterName": "aurora.logical_replication_globaldb", "ParameterValue": "0"}]},
            {"DBClusterParameterGroupName": "orders-zero-etl", "Marker": "m1"})
        values = p.cluster_parameters(rds, "orders-zero-etl")
    assert p.check_parameters("aurora-postgresql", values) == [
        "aurora.logical_replication_backup is '1', must be '0'"]


def test_data_filter():
    assert p.data_filter("aurora-postgresql", ["orders.*.*"], ["orders.audit.*", "orders.public./tmp_.*/"]) == \
        "include: orders.*.*, exclude: orders.audit.*, exclude: orders.public./tmp_.*/"
    assert p.data_filter("aurora-mysql", ["books./table_\\d+/"]) == "include: books./table_\\d+/"
    with pytest.raises(ValueError, match="database.schema.table"):
        p.data_filter("aurora-postgresql", ["orders.*"])
    with pytest.raises(ValueError, match="at least one include"):
        p.data_filter("aurora-postgresql", [], ["orders.audit.*"])
    with pytest.raises(ValueError, match="regular expression for the database"):
        p.data_filter("aurora-postgresql", ["/ord.*/.*.*"])


def test_create_requests_match_models_and_tolerate_existing():
    rds, rs = client("rds"), client("redshift")
    policy = json.dumps(p.target_policy(SRC, "111122223333", NS))
    with Stubber(rds) as r, Stubber(rs) as s:
        s.add_response("put_resource_policy", {"ResourcePolicy": {"ResourceArn": NS, "Policy": policy}},
                       {"ResourceArn": NS, "Policy": policy})
        r.add_client_error("create_integration", "IntegrationAlreadyExistsFault", http_status_code=400,
                           expected_params={"SourceArn": SRC, "TargetArn": NS, "IntegrationName": "orders-to-redshift",
                                            "KMSKeyId": "alias/orders-zero-etl", "DataFilter": "include: orders.*.*"})
        r.add_response("describe_integrations", {"Integrations": [{
            "SourceArn": SRC, "TargetArn": NS, "IntegrationName": "orders-to-redshift",
            "IntegrationArn": "arn:aws:rds:eu-west-1:111122223333:integration:abc", "Status": "active",
            "CreateTime": NOW}]}, {})
        arn = p.create(rds, rs, name="orders-to-redshift", source_arn=SRC, namespace_arn=NS,
                       account_id="111122223333", kms_key_id="alias/orders-zero-etl",
                       data_filter_expr="include: orders.*.*")
    assert arn.endswith(":integration:abc")


def test_target_policy_conditions():
    pol = p.target_policy(SRC, "111122223333", NS)
    assert pol["Statement"][0]["Condition"]["StringEquals"]["aws:SourceArn"] == SRC
    assert pol["Statement"][1]["Principal"]["AWS"] == "arn:aws:iam::111122223333:root"


@pytest.mark.skipif("PG_DSN" not in os.environ, reason="set PG_DSN to run against PostgreSQL")
def test_no_pk_query_against_postgres():
    import psycopg
    with psycopg.connect(os.environ["PG_DSN"], autocommit=True) as conn:
        conn.execute("DROP SCHEMA IF EXISTS zetl CASCADE; CREATE SCHEMA zetl")
        conn.execute("CREATE TABLE zetl.orders (id bigint PRIMARY KEY, total numeric)")
        conn.execute("CREATE TABLE zetl.events (at timestamptz, payload jsonb)")
        conn.execute("CREATE TABLE zetl.sales (id bigint, day date, PRIMARY KEY (id, day)) PARTITION BY RANGE (day)")
        conn.execute("CREATE TABLE zetl.sales_2026 PARTITION OF zetl.sales FOR VALUES FROM ('2026-01-01') TO ('2027-01-01')")
        conn.execute("CREATE TABLE zetl.logs (msg text) PARTITION BY LIST (msg)")
        rows = [r for r in conn.execute(p.NO_PK_SQL).fetchall() if r[0] == "zetl"]
        conn.execute("DROP SCHEMA zetl CASCADE")
    assert rows == [("zetl", "events"), ("zetl", "logs")]
