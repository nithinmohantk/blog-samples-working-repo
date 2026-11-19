# s3tables-starter

Sample code for the dataa.dev article *Amazon S3 Tables & Apache Iceberg: Native Lakehouse in S3, 14 Months Later* (21 February 2026).

## What is here

| File | Purpose |
| --- | --- |
| `s3tables_setup.py` | Creates a table bucket, namespace and table (schema, partition spec, sort order) idempotently, sets compaction and snapshot management per table and unreferenced file removal per bucket, flags tables whose managed snapshot expiry would fail, and builds PyIceberg properties for the S3 Tables Iceberg REST endpoint. |
| `cost_model.py` | Monthly cost estimate for one table from S3 Tables price dimensions. Defaults are AWS's published US West (Oregon) example rates after the July 2025 compaction price cut. |
| `tests/` | 14 pytest tests. |

## Run the tests

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
pytest -q
```

## Run against AWS

`python s3tables_setup.py` creates `finance-lakehouse`, namespace `finance` and table `payments` in the Region of your default AWS profile. The caller needs `s3tables:CreateTableBucket`, `ListTableBuckets`, `CreateNamespace`, `CreateTable`, `GetTable`, `PutTableMaintenanceConfiguration` and `PutTableBucketMaintenanceConfiguration`. Delete the resources afterwards to avoid storage and monitoring charges.

## What has been verified

- Tested with Python 3.13, `boto3==1.42.50` (16 February 2026) and `pytest==9.0.2`.
- Every request in the tests goes through botocore's Stubber, which validates parameters and responses against the S3 Tables API model shipped in that botocore release.
- The cost test reproduces AWS's published example ($28.54) to the cent.
- Nothing has been run against a live AWS account.
