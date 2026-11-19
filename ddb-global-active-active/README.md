# Active-active orders API on DynamoDB global tables

Sample code for the dataa.dev article *Multi-Region Active-Active Serverless Patterns with Global Tables* (17 April 2026).

| File | What it is |
| :--- | :--- |
| `app/orders.py` | Order writes in the "write to your Region" pattern: idempotent creates keyed by the client's `Idempotency-Key`, a home Region per order, updates only in the home Region with an optimistic version check |
| `app/handlers.py` | Lambda handlers for a Regional API Gateway HTTP API (payload 2.0): `POST /orders`, `PATCH /orders/{order_id}`, `GET /health` for a Route 53 health check |
| `template.yaml` | `AWS::DynamoDB::GlobalTable` in MREC mode, on-demand, replicas in eu-west-1 and us-east-1 |
| `template-mrsc.yaml` | `AWS::DynamoDB::GlobalTable` in MRSC mode: two replicas and a witness in the US Region set |

The same Lambda code is deployed to each Region and reads and writes only the local replica (`AWS_REGION`). An update that arrives in the wrong Region gets HTTP 421 with an `x-home-region` header so the client, or a routing layer, retries in the right place.

## Test

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
python -m pytest -q
cfn-lint template.yaml template-mrsc.yaml
```

## What was verified

- Eight tests pass with Python 3.13, `boto3==1.42.89` (13 April 2026) and `moto==5.1.22`: idempotent replay returns the same order, a reused key with a different body is rejected, input validation, the version check, redirect from a non-home Region, the health endpoint (healthy, drained, and table unreachable).
- Both templates pass `cfn-lint==1.48.1` (1 April 2026). The linter rejects a misspelled `MultiRegionConsistency` property, so a clean result means the property names match the CloudFormation schema of that release.
- Not verified: replication between Regions (moto and DynamoDB Local do not replicate), deployment, Route 53 records. Those need an AWS account.
