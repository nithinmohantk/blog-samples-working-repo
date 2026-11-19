"""Reads the facts the checks need from a running PostgreSQL database.

Read-only queries against system catalogs; run with a role that can read
pg_extension, pg_replication_slots and pg_stat_activity (pg_monitor is enough).
"""
from __future__ import annotations

import psycopg

from .checks import SourceFacts

TABLES_WITHOUT_PK = """
SELECT n.nspname || '.' || c.relname
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind IN ('r', 'p')
  AND n.nspname NOT IN ('pg_catalog', 'information_schema')
  AND n.nspname NOT LIKE 'pg_toast%'
  AND NOT EXISTS (SELECT 1 FROM pg_constraint k WHERE k.conrelid = c.oid AND k.contype = 'p')
ORDER BY 1
"""


def collect(conninfo: str, **inventory) -> SourceFacts:
    """Collect facts. `inventory` supplies what SQL cannot see, for example
    uses_geo_replica=True or needs_vnet_injection=True."""
    with psycopg.connect(conninfo, autocommit=True, connect_timeout=10) as conn, conn.cursor() as cur:
        cur.execute("SET statement_timeout = '30s'")
        cur.execute("SELECT current_setting('server_version_num')::int, "
                    "current_setting('max_connections')::int, pg_database_size(current_database())")
        version_num, max_conn, size = cur.fetchone()
        cur.execute("SELECT extname, extversion FROM pg_extension")
        extensions = dict(cur.fetchall())
        cur.execute("SELECT count(*) FROM pg_replication_slots WHERE slot_type = 'logical'")
        (slots,) = cur.fetchone()
        cur.execute(TABLES_WITHOUT_PK)
        no_pk = [r[0] for r in cur.fetchall()]
        cur.execute("SELECT count(*) FROM pg_stat_activity WHERE backend_type = 'client backend'")
        (current_conn,) = cur.fetchone()
    return SourceFacts(
        server_version_num=version_num,
        extensions=extensions,
        logical_slots=slots,
        tables_without_pk=no_pk,
        database_bytes=size,
        max_connections=max_conn,
        peak_connections=inventory.pop("peak_connections", current_conn),
        **inventory,
    )
