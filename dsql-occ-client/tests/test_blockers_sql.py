"""Runs dsql_blockers.sql against a real PostgreSQL server.

Set BLOCKERS_TEST_DSN to a throwaway database, for example
postgresql://postgres@localhost:55432/postgres. The test creates and drops its
own schema. It is skipped when the variable is not set.
"""

import os
from pathlib import Path

import psycopg
import pytest

DSN = os.environ.get("BLOCKERS_TEST_DSN")
SQL = (Path(__file__).resolve().parent.parent / "dsql_blockers.sql").read_text()
pytestmark = pytest.mark.skipif(not DSN, reason="BLOCKERS_TEST_DSN not set")

SCHEMA = """
DROP SCHEMA IF EXISTS legacy CASCADE;
CREATE SCHEMA legacy;
CREATE TABLE legacy.customers (id bigserial PRIMARY KEY, email text NOT NULL);
CREATE TABLE legacy.orders (
    id uuid PRIMARY KEY,
    customer_id bigint REFERENCES legacy.customers(id),
    total numeric(12, 2) NOT NULL,
    updated_at timestamptz
);
CREATE TABLE legacy.wide (id int PRIMARY KEY);
CREATE FUNCTION legacy.touch() RETURNS trigger LANGUAGE plpgsql AS
  $$ BEGIN NEW.updated_at := now(); RETURN NEW; END $$;
CREATE TRIGGER orders_touch BEFORE UPDATE ON legacy.orders FOR EACH ROW EXECUTE FUNCTION legacy.touch();
CREATE FUNCTION legacy.order_total(o legacy.orders) RETURNS numeric LANGUAGE sql AS $$ SELECT o.total $$;
"""


@pytest.fixture()
def conn():
    with psycopg.connect(DSN, autocommit=True) as c:
        c.execute(SCHEMA)
        for i in range(25):
            c.execute(f"CREATE INDEX wide_i{i} ON legacy.wide ((id + {i}))")
        yield c
        c.execute("DROP SCHEMA legacy CASCADE")


def test_blockers_found(conn):
    rows = conn.execute(SQL).fetchall()
    found = {(category, obj) for category, obj, _ in rows}
    assert ("trigger", "legacy.orders: orders_touch") in found
    assert ("procedural function", "legacy.touch (plpgsql)") in found
    assert ("sequence or identity", "legacy.customers_id_seq") in found
    assert ("foreign key", "legacy.orders: orders_customer_id_fkey") in found
    assert ("too many indexes", "legacy.wide (26 indexes)") in found
    # SQL-language functions are supported by Aurora DSQL and must not be reported.
    assert not any("order_total" in obj for _, obj in found)
