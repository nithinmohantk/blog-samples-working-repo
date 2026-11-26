"""ImportTable: the older S3 import, which can only create a new table."""
from __future__ import annotations

import time

from .common import TAG, bucket, client, key_schema


def run(table: str, prefix: str, poll: float = 15.0) -> dict:
    ddb = client("dynamodb")
    schema = key_schema()
    resp = ddb.import_table(
        S3BucketSource={"S3Bucket": bucket(), "S3KeyPrefix": prefix},
        InputFormat="DYNAMODB_JSON",
        InputCompressionType="GZIP",
        TableCreationParameters={
            "TableName": table,
            "AttributeDefinitions": schema["AttributeDefinitions"],
            "KeySchema": schema["KeySchema"],
            "BillingMode": "PAY_PER_REQUEST",
            "GlobalSecondaryIndexes": schema["GlobalSecondaryIndexes"],
        },
    )
    arn = resp["ImportTableDescription"]["ImportArn"]
    while True:
        desc = ddb.describe_import(ImportArn=arn)["ImportTableDescription"]
        if desc["ImportStatus"] in ("COMPLETED", "FAILED", "CANCELLED"):
            break
        time.sleep(poll)
    # ImportTable cannot tag at creation; tag afterwards so teardown can find it.
    if desc["ImportStatus"] == "COMPLETED":
        ddb.tag_resource(ResourceArn=desc["TableArn"], Tags=[TAG])
    return desc
