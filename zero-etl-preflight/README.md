# zero-etl-preflight

Sample code for the dataa.dev article *Zero-ETL Analytics: Amazon Aurora to Redshift Continuous Sync* (28 April 2026).

## What is here

| File | Purpose |
| --- | --- |
| `preflight.py` | Checks an Aurora MySQL or Aurora PostgreSQL DB cluster parameter group against the values zero-ETL requires; builds data filter expressions in the documented syntax and rejects invalid patterns; builds the Redshift resource policy that authorizes the source; creates the integration idempotently; and holds a SQL query that lists Aurora PostgreSQL tables without a primary key. |
| `tests/` | 6 pytest tests. |

## Run the tests

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
pytest -q
# optional: run the SQL test against a PostgreSQL 16 server
PG_DSN="host=localhost dbname=postgres user=postgres" pytest -q
```

## What has been verified

- Tested with Python 3.13, `boto3==1.42.95` (23 April 2026), `psycopg[binary]==3.3.2` and `pytest==9.0.2`. RDS and Redshift calls go through botocore's Stubber, which validates them against the API models in that release.
- The primary-key query was run against PostgreSQL 16; it skips partitions and flags partitioned parents without a key.
- Nothing has been run against Aurora or Redshift.
