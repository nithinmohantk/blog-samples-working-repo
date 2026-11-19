"""Measures how a selective filter interacts with an HNSW vector index.

An HNSW scan finds `hnsw.ef_search` nearest candidates first and applies the
WHERE clause afterwards. When the filter keeps only a small share of rows, a
query asking for 10 neighbours can return fewer than 10. pgvector 0.8.0
(the version on HorizonDB) adds iterative index scans, and HorizonDB's
pg_diskann pushes filters into the vector search; this script measures the
problem itself, on whatever pgvector version the server has.

Usage: python vector_filter.py "postgresql://..."   (creates and drops table vf_docs)
"""
from __future__ import annotations

import statistics
import sys
from dataclasses import dataclass

import psycopg

DIM = 64


@dataclass
class Result:
    ef_search: int
    mean_rows: float
    min_rows: int
    mean_recall: float


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


def run(conn: psycopg.Connection, ef_values=(40, 100, 400), k: int = 10, queries: int = 20, tenant: int = 7) -> list[Result]:
    qs = _query_vectors(conn, queries)
    results = []
    with conn.cursor() as cur:
        # Exact answers: no vector index, filter first, then sort.
        cur.execute("BEGIN")
        cur.execute("SET LOCAL enable_indexscan = off")
        cur.execute("SET LOCAL enable_bitmapscan = on")
        exact = [set(_ids(cur, tenant, q, k)) for q in qs]
        cur.execute("COMMIT")
        for ef in ef_values:
            cur.execute("BEGIN")
            cur.execute(f"SET LOCAL hnsw.ef_search = {int(ef)}")
            cur.execute("SET LOCAL enable_seqscan = off")
            cur.execute("SET LOCAL enable_bitmapscan = off")
            plan = "\n".join(r[0] for r in cur.execute(
                "EXPLAIN SELECT id FROM vf_docs WHERE tenant_id = 7 ORDER BY embedding <=> %s::vector LIMIT 10", (qs[0],)))
            assert "vf_docs_hnsw" in plan, plan
            got = [_ids(cur, tenant, q, k) for q in qs]
            cur.execute("COMMIT")
            counts = [len(g) for g in got]
            recall = [len(set(g) & e) / k for g, e in zip(got, exact)]
            results.append(Result(ef, statistics.mean(counts), min(counts), statistics.mean(recall)))
    return results


def main(conninfo: str) -> None:
    with psycopg.connect(conninfo, autocommit=True) as conn:
        setup(conn)
        server = conn.execute("SELECT current_setting('server_version')").fetchone()[0]
        version = conn.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'").fetchone()[0]
        print(f"PostgreSQL {server}, pgvector {version}; 20,000 rows, 50 tenants (2% per tenant), k = 10")
        for r in run(conn):
            print(f"ef_search={r.ef_search:>4}: rows returned mean {r.mean_rows:5.1f}, min {r.min_rows:2d}; "
                  f"recall@10 {r.mean_recall:.2f}")
        conn.execute("DROP TABLE vf_docs")


if __name__ == "__main__":
    main(sys.argv[1])
