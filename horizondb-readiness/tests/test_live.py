"""Runs the collector, the CLI and the vector measurement against a real PostgreSQL
started with pgserver (PostgreSQL 16.2 with pgvector 0.6.2)."""
import json
import tempfile

import psycopg
import pytest

pgserver = pytest.importorskip("pgserver")

from horizondb_readiness.__main__ import main
from horizondb_readiness.checks import Severity, assess
from horizondb_readiness.collect import collect
import vector_filter


@pytest.fixture(scope="module")
def uri():
    srv = pgserver.get_server(tempfile.mkdtemp(prefix="hzt"), cleanup_mode="stop")
    u = srv.get_uri()
    with psycopg.connect(u, autocommit=True) as c:
        c.execute("CREATE EXTENSION IF NOT EXISTS vector")
        c.execute("DROP TABLE IF EXISTS audit_log, patients")
        c.execute("CREATE TABLE patients (id bigint PRIMARY KEY, name text)")
        c.execute("CREATE TABLE audit_log (at timestamptz, entry text)")  # no primary key
    yield u


def test_collect_reads_the_catalog(uri):
    f = collect(uri)
    assert f.major == 16
    assert f.extensions["vector"] == "0.6.2"
    assert "public.audit_log" in f.tables_without_pk and "public.patients" not in f.tables_without_pk
    assert f.logical_slots == 0 and f.database_bytes > 0


def test_findings_for_a_pg16_source(uri):
    out = assess(collect(uri))
    by_code = {x.code: x for x in out}
    assert by_code["major_version"].severity is Severity.BLOCKER
    assert by_code["extension:vector"].severity is Severity.INFO  # 0.6.2 -> 0.8.7
    assert by_code["no_primary_key"].severity is Severity.ACTION


def test_cli_exit_codes_and_json(uri, capsys):
    assert main([uri, "--json"]) == 2
    report = json.loads(capsys.readouterr().out)
    assert report["summary"]["blocker"] == 1
    assert main(["postgresql://nobody@127.0.0.1:1/x?connect_timeout=2"]) == 1


def test_selective_filter_starves_hnsw(uri):
    with psycopg.connect(uri, autocommit=True) as conn:
        vector_filter.setup(conn, rows=20_000, tenants=50)
        res = {r.ef_search: r for r in vector_filter.run(conn, ef_values=(40, 400))}
        conn.execute("DROP TABLE vf_docs")
    assert res[40].mean_rows < 3 and res[40].min_rows == 0     # far fewer than k = 10
    assert res[400].mean_rows > 5 and res[400].mean_recall > res[40].mean_recall
