"""Measures how a selective filter interacts with an HNSW vector index.

An HNSW scan finds `hnsw.ef_search` nearest candidates first and applies the
WHERE clause afterwards. When the filter keeps only a small share of rows, a
query asking for 10 neighbours can return fewer than 10. pgvector 0.8.0
(the version on HorizonDB) adds iterative index scans, and HorizonDB's
pg_diskann pushes filters into the vector search; this script measures the
problem itself, on whatever pgvector version the server has. On pgvector
0.8.0 or later it also measures iterative scans (`hnsw.iterative_scan`
strict_order and relaxed_order), and if the pg_diskann extension can be
created it measures a DiskANN index on the same data.

Usage: python vector_filter.py "postgresql://..."   (creates and drops table vf_docs)
"""
from __future__ import annotations

import statistics
import sys
import time
from dataclasses import dataclass

import psycopg

DIM = 64


@dataclass
class Result:
    ef_search: int
    mean_rows: float
    min_rows: int
    mean_recall: float
    mode: str = "off"
    mean_ms: float = 0.0


def setup(conn: psycopg.Connection, rows: int = 20_000, tenants: int = 50, seed: float = 0.42) -> None:
    with conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
        cur.execute("DROP TABLE IF EXISTS vf_docs")
        cur.execute(f"CREATE TABLE vf_docs (id int PRIMARY KEY, tenant_id int NOT NULL, embedding vector({DIM}) NOT NULL)")
        cur.execute("SELECT setseed(%s)", (seed,))
        cur.execute(
            f"""INSERT INTO vf_docs
                SELECT i, i %% %s, v.a::vector
                FROM generate_series(1, %s) AS i,
                     LATERAL (SELECT array_agg(random() - 0.5) AS a FROM generate_series(1, {DIM}) WHERE i > 0) AS v""",
            (tenants, rows),
        )
        cur.execute("CREATE INDEX vf_docs_hnsw ON vf_docs USING hnsw (embedding vector_cosine_ops)")
        cur.execute("CREATE INDEX vf_docs_tenant ON vf_docs (tenant_id)")
        cur.execute("ANALYZE vf_docs")


def _query_vectors(conn: psycopg.Connection, n: int) -> list[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT setseed(0.7)")
        cur.execute(f"SELECT v.a::vector::text FROM generate_series(1, %s) AS g, "
                    f"LATERAL (SELECT array_agg(random() - 0.5) AS a FROM generate_series(1, {DIM}) WHERE g > 0) AS v",
                    (n,))
        return [r[0] for r in cur.fetchall()]


def _ids(cur: psycopg.Cursor, tenant: int, q: str, k: int) -> list[int]:
    cur.execute("SELECT id FROM vf_docs WHERE tenant_id = %s ORDER BY embedding <=> %s::vector LIMIT %s", (tenant, q, k))
    return [r[0] for r in cur.fetchall()]


def _exact(conn: psycopg.Connection, qs: list[str], tenant: int, k: int) -> list[set[int]]:
    """Exact answers: no vector index, filter first, then sort."""
    with conn.cursor() as cur:
        cur.execute("BEGIN")
        cur.execute("SET LOCAL enable_indexscan = off")
        cur.execute("SET LOCAL enable_bitmapscan = on")
        exact = [set(_ids(cur, tenant, q, k)) for q in qs]
        cur.execute("COMMIT")
    return exact


def _measure(conn: psycopg.Connection, settings: list[str], index: str, label: int, mode: str,
             qs: list[str], exact: list[set[int]], tenant: int, k: int) -> Result:
    with conn.cursor() as cur:
        cur.execute("BEGIN")
        for setting in settings:
            cur.execute(setting)
        cur.execute("SET LOCAL enable_seqscan = off")
        cur.execute("SET LOCAL enable_bitmapscan = off")
        plan = "\n".join(r[0] for r in cur.execute(
            "EXPLAIN SELECT id FROM vf_docs WHERE tenant_id = 7 ORDER BY embedding <=> %s::vector LIMIT 10", (qs[0],)))
        assert index in plan, plan
        got, times = [], []
        for q in qs:
            t0 = time.perf_counter()
            got.append(_ids(cur, tenant, q, k))
            times.append((time.perf_counter() - t0) * 1000)
        cur.execute("COMMIT")
    counts = [len(g) for g in got]
    recall = [len(set(g) & e) / k for g, e in zip(got, exact)]
    return Result(label, statistics.mean(counts), min(counts), statistics.mean(recall), mode, statistics.median(times))


def run(conn: psycopg.Connection, ef_values=(40, 100, 400), k: int = 10, queries: int = 20, tenant: int = 7,
        modes=("off",)) -> list[Result]:
    qs = _query_vectors(conn, queries)
    exact = _exact(conn, qs, tenant, k)
    results = []
    for mode in modes:
        for ef in ef_values:
            settings = [f"SET LOCAL hnsw.ef_search = {int(ef)}"]
            if mode != "off":
                settings.append(f"SET LOCAL hnsw.iterative_scan = {mode}")
            results.append(_measure(conn, settings, "vf_docs_hnsw", ef, mode, qs, exact, tenant, k))
    return results


def run_diskann(conn: psycopg.Connection, k: int = 10, queries: int = 20, tenant: int = 7) -> Result | None:
    """Builds a DiskANN index if pg_diskann is available, measures it, and drops it again."""
    try:
        conn.execute("CREATE EXTENSION IF NOT EXISTS pg_diskann CASCADE")
    except psycopg.Error as e:
        print(f"pg_diskann not measured: {e.diag.message_primary or e}")
        return None
    conn.execute("DROP INDEX vf_docs_hnsw")
    conn.execute("CREATE INDEX vf_docs_diskann ON vf_docs USING diskann (embedding vector_cosine_ops)")
    conn.execute("ANALYZE vf_docs")
    qs = _query_vectors(conn, queries)
    exact = _exact(conn, qs, tenant, k)
    return _measure(conn, [], "vf_docs_diskann", 0, "diskann", qs, exact, tenant, k)


def _version(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in v.split(".")[:3] if x.isdigit())


def main(conninfo: str) -> None:
    with psycopg.connect(conninfo, autocommit=True) as conn:
        setup(conn)
        server = conn.execute("SELECT current_setting('server_version')").fetchone()[0]
        version = conn.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'").fetchone()[0]
        print(f"PostgreSQL {server}, pgvector {version}; 20,000 rows, 50 tenants (2% per tenant), k = 10")
        modes = ("off", "strict_order", "relaxed_order") if _version(version) >= (0, 8, 0) else ("off",)
        for r in run(conn, modes=modes):
            prefix = "" if len(modes) == 1 else f"iterative_scan={r.mode:<13} "
            print(f"{prefix}ef_search={r.ef_search:>4}: rows returned mean {r.mean_rows:5.1f}, min {r.min_rows:2d}; "
                  f"recall@10 {r.mean_recall:.2f}" + (f"; median {r.mean_ms:.1f} ms" if len(modes) > 1 else ""))
        if len(modes) > 1:
            d = run_diskann(conn)
            if d:
                print(f"pg_diskann (default settings)          : rows returned mean {d.mean_rows:5.1f}, "
                      f"min {d.min_rows:2d}; recall@10 {d.mean_recall:.2f}; median {d.mean_ms:.1f} ms")
        conn.execute("DROP TABLE vf_docs")


if __name__ == "__main__":
    main(sys.argv[1])
