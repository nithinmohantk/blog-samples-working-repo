import importlib
import json
import os
import sys

import boto3
import pytest
from moto import mock_aws

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


@pytest.fixture()
def env(monkeypatch):
    for k, v in {"AWS_ACCESS_KEY_ID": "x", "AWS_SECRET_ACCESS_KEY": "x",
                 "AWS_REGION": "eu-west-1", "AWS_DEFAULT_REGION": "eu-west-1", "TABLE_NAME": "orders"}.items():
        monkeypatch.setenv(k, v)
    with mock_aws():
        boto3.client("dynamodb", region_name="eu-west-1").create_table(
            TableName="orders", BillingMode="PAY_PER_REQUEST",
            AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}],
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}])
        import app.handlers as handlers
        importlib.reload(handlers)  # bind clients inside the mock
        yield handlers


def _post(h, key, body):
    return h.create_order_handler({"headers": {"Idempotency-Key": key}, "body": json.dumps(body)}, None)


def _patch(h, order_id, body):
    return h.update_status_handler({"pathParameters": {"order_id": order_id}, "body": json.dumps(body)}, None)


def test_create_is_idempotent(env):
    first = _post(env, "k-1", {"customer_id": "c1", "amount": "19.99"})
    again = _post(env, "k-1", {"customer_id": "c1", "amount": "19.99"})
    assert first["statusCode"] == 201 and again["statusCode"] == 200
    assert json.loads(first["body"]) == json.loads(again["body"])
    body = json.loads(first["body"])
    assert body["home_region"] == "eu-west-1" and body["amount"] == "19.99" and body["version"] == 1
    assert "request_fingerprint" not in body


def test_reused_key_with_different_body_is_rejected(env):
    _post(env, "k-2", {"customer_id": "c1", "amount": "10"})
    assert _post(env, "k-2", {"customer_id": "c1", "amount": "11"})["statusCode"] == 409


def test_validation(env):
    assert _post(env, "", {"customer_id": "c1", "amount": "1"})["statusCode"] == 400
    assert _post(env, "k-3", {"customer_id": "c1", "amount": "-1"})["statusCode"] == 400
    assert _post(env, "k-4", {"customer_id": "c1", "amount": "1.001"})["statusCode"] == 400


def test_versioned_update_and_conflict(env):
    _post(env, "k-5", {"customer_id": "c1", "amount": "5"})
    ok = _patch(env, "k-5", {"status": "PAID", "expected_version": 1})
    assert ok["statusCode"] == 200 and json.loads(ok["body"])["version"] == 2
    stale = _patch(env, "k-5", {"status": "SHIPPED", "expected_version": 1})
    assert stale["statusCode"] == 409


def test_update_outside_home_region_is_redirected(env):
    from app import orders
    table = boto3.resource("dynamodb", region_name="eu-west-1").Table("orders")
    orders.create_order(table, "us-east-1", "k-6", "c1", "7")  # homed in us-east-1
    resp = _patch(env, "k-6", {"status": "PAID", "expected_version": 1})
    assert resp["statusCode"] == 421 and resp["headers"]["x-home-region"] == "us-east-1"


def test_unknown_order_and_bad_status(env):
    assert _patch(env, "nope", {"status": "PAID", "expected_version": 1})["statusCode"] == 404
    _post(env, "k-7", {"customer_id": "c1", "amount": "1"})
    assert _patch(env, "k-7", {"status": "LOST", "expected_version": 1})["statusCode"] == 400


def test_health(env, monkeypatch):
    assert env.health_handler({}, None)["statusCode"] == 200
    monkeypatch.setenv("REGION_DRAINED", "true")
    assert env.health_handler({}, None)["statusCode"] == 503


def test_health_fails_when_table_missing(env):
    boto3.client("dynamodb", region_name="eu-west-1").delete_table(TableName="orders")
    assert json.loads(env.health_handler({}, None)["body"])["reason"] == "dynamodb"
