# dsql-occ-client

Sample code for the dataa.dev article *Amazon Aurora DSQL in Production: What Enterprise Architects Need to Know* (3 February 2026).

## What is here

- `dsql_client.py`: helpers for Python applications on Aurora DSQL with psycopg 3.
  - `TokenProvider` generates IAM authentication tokens with boto3 (locally, using SigV4) and refreshes them before they expire.
  - `connect()` opens a TLS connection to the cluster's `postgres` database.
  - `Session.run()` runs a function in one transaction and retries the whole transaction on SQLSTATE 40001 (OC000 data conflicts and OC001 schema conflicts), with full-jitter backoff. It reopens the connection if it has closed, since Aurora DSQL ends connections after 60 minutes.
  - `write_in_batches()` splits a load into transactions below the 3,000-row limit.
- `dsql_blockers.sql`: a read-only query to run against the source PostgreSQL database. It lists triggers, procedural (non-SQL) functions, sequences and identity columns, foreign keys, extensions, and tables over Aurora DSQL's 24-index or 255-column limits.

## Run it

```bash
python3.13 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
pytest -q

# The SQL test needs a throwaway PostgreSQL database:
BLOCKERS_TEST_DSN="postgresql://postgres@localhost:5432/postgres" pytest -q tests/test_blockers_sql.py

# Against your own source database (read-only):
psql "$SOURCE_DSN" -f dsql_blockers.sql
```

Using the client:

```python
from dsql_client import Session, TokenProvider, connect

provider = TokenProvider("<cluster-id>.dsql.eu-west-1.on.aws", "eu-west-1", admin=True)
session = Session(lambda: connect(provider))
session.run(lambda cur: cur.execute(
    "UPDATE accounts SET balance = balance - %s WHERE id = %s", (25, account_id)))
```

## What has been verified

- 10 unit tests pass on Python 3.13 with `boto3==1.42.39` (30 January 2026), `psycopg[binary]==3.3.2` and `pytest==9.0.2`. They check token format and refresh, retry and backoff on OC000 and OC001, no retry on other errors, reconnecting after a closed connection, and batching.
- `dsql_blockers.sql` is tested against PostgreSQL 16 with a schema containing a trigger, a PL/pgSQL function, a `bigserial` column, a foreign key and a table with 26 indexes.
- Nothing here has been run against a live Aurora DSQL cluster; the retry behaviour follows the Aurora DSQL concurrency control documentation.
