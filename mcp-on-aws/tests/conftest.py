import os
import sys
from decimal import Decimal

import boto3
import pytest
from moto import mock_aws

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

TABLE = "CustomerOrders"

# Synthetic fixture: 30 orders for C-000001, 2 for C-000002.
ORDERS = [("C-000001", f"O-{i:04d}", Decimal(f"{10 + i}.50"), "SHIPPED") for i in range(30)] + [
    ("C-000002", "O-9001", Decimal("99.99"), "PENDING"),
    ("C-000002", "O-9002", Decimal("0.01"), "CANCELLED"),
]


@pytest.fixture()
def orders_table(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-west-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("ORDERS_TABLE_NAME", TABLE)
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name="eu-west-1")
        table = ddb.create_table(
            TableName=TABLE,
            KeySchema=[
                {"AttributeName": "customer_id", "KeyType": "HASH"},
                {"AttributeName": "order_id", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "customer_id", "AttributeType": "S"},
                {"AttributeName": "order_id", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        with table.batch_writer() as batch:
            for cid, oid, amount, status in ORDERS:
                batch.put_item(Item={"customer_id": cid, "order_id": oid, "amount": amount, "status": status})
        import sales_tools

        sales_tools.reset_table_cache()
        yield table
        sales_tools.reset_table_cache()


def expected_total(customer_id):
    return float(sum(a for c, _, a, _ in ORDERS if c == customer_id))
