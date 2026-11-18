"""Build HNSW indexes under different settings and measure each build.

    python bench/run.py --dsn postgresql://postgres:pw@localhost:5432/postgres \
        --label 0.6.0/shm-2g --experiments parallel-1gb serial-1gb --out results.json

For each experiment: build time, parallel workers seen in pg_stat_activity,
notices, WAL written, index size, and recall@10 at two ef_search values.
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
import threading
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path

import numpy as np
import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dataset import exact_neighbours, fingerprint, generate, recall_at_k  # noqa: E402

M, EF_CONSTRUCTION = 16, 64
EF_SEARCH = (40, 100)

EXPERIMENTS = {
    # name: (maintenance_work_mem, max_parallel_maintenance_workers)
    "default-mem": ("64MB", 3),
    "serial-1gb": ("1GB", 0),
    "parallel-1gb": ("1GB", 3),
    "parallel-1gb-unlogged": ("1GB", 3),  # same, with the table switched to UNLOGGED first
    "default-workers-1gb": ("1GB", None),  # max_parallel_maintenance_workers left at the server default
}


@dataclass
class Result:
    label: str
    experiment: str
    maintenance_work_mem: str
    workers_requested: int | None
    pgvector: str = ""
    seconds: float | None = None
    max_parallel_workers_seen: int = 0
    phases_seen: list[str] = field(default_factory=list)
    notices: list[str] = field(default_factory=list)
    error: str | None = None
    wal_bytes: int | None = None
    index_bytes: int | None = None
    recall: dict[str, float] = field(default_factory=dict)
    query_ms_mean: dict[str, float] = field(default_factory=dict)
    plan_uses_index: bool | None = None


def binary_copy(vectors: np.ndarray) -> bytes:
    """PGCOPY binary stream for (id int4, embedding vector) rows.

    pgvector's binary format is int16 dimensions, int16 unused, then float4 values.
    """
    n, dim = vectors.shape
    row = np.dtype([("fields", ">i2"), ("id_len", ">i4"), ("id", ">i4"), ("vec_len", ">i4"),
                    ("dim", ">i2"), ("unused", ">i2"), ("values", ">f4", (dim,))])
    rows = np.empty(n, dtype=row)
    rows["fields"], rows["id_len"], rows["id"] = 2, 4, np.arange(n)
    rows["vec_len"], rows["dim"], rows["unused"] = 4 + 4 * dim, dim, 0
    rows["values"] = vectors
    header = b"PGCOPY\n\xff\r\n\x00" + struct.pack(">ii", 0, 0)
    return header + rows.tobytes() + struct.pack(">h", -1)


def ensure_table(conn: psycopg.Connection, train: np.ndarray) -> None:
    conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    exists = conn.execute("SELECT to_regclass('items') IS NOT NULL").fetchone()[0]
    if exists and conn.execute("SELECT count(*) FROM items").fetchone()[0] == len(train):
        return
    conn.execute("DROP TABLE IF EXISTS items")
    conn.execute(f"CREATE TABLE items (id int4 PRIMARY KEY, embedding vector({train.shape[1]}))")
    with conn.cursor().copy("COPY items (id, embedding) FROM STDIN WITH (FORMAT binary)") as copy:
        copy.write(binary_copy(train))
    conn.execute("VACUUM ANALYZE items")


class Watcher(threading.Thread):
    """Polls a second connection while the index builds."""

    def __init__(self, dsn: str):
        super().__init__(daemon=True)
        self.dsn, self.stop, self.max_workers, self.phases = dsn, threading.Event(), 0, []

    def run(self) -> None:
        with psycopg.connect(self.dsn, autocommit=True) as conn:
            while not self.stop.is_set():
                workers = conn.execute(
                    "SELECT count(*) FROM pg_stat_activity WHERE backend_type = 'parallel worker'").fetchone()[0]
                self.max_workers = max(self.max_workers, workers)
                for (phase,) in conn.execute("SELECT phase FROM pg_stat_progress_create_index").fetchall():
                    if not self.phases or self.phases[-1] != phase:
                        self.phases.append(phase)
                time.sleep(0.2)


def build_and_measure(dsn: str, label: str, name: str, test: np.ndarray, truth: np.ndarray) -> Result:
    mem, workers = EXPERIMENTS[name]
    result = Result(label, name, mem, workers)
    with psycopg.connect(dsn, autocommit=True) as conn:
        result.pgvector = conn.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'").fetchone()[0]
        conn.add_notice_handler(lambda d: result.notices.append(f"{d.severity}: {d.message_primary}"))
        conn.execute("DROP INDEX IF EXISTS items_embedding_hnsw")
        unlogged = name.endswith("-unlogged")
        conn.execute("ALTER TABLE items SET UNLOGGED" if unlogged else "ALTER TABLE items SET LOGGED")
        conn.execute("CHECKPOINT")
        conn.execute(f"SET maintenance_work_mem = '{mem}'")
        if workers is not None:
            conn.execute(f"SET max_parallel_maintenance_workers = {workers}")
        else:
            result.workers_requested = int(conn.execute("SHOW max_parallel_maintenance_workers").fetchone()[0])
        wal_before = conn.execute("SELECT pg_current_wal_lsn()").fetchone()[0]
        watcher = Watcher(dsn)
        watcher.start()
        started = time.perf_counter()
        try:
            conn.execute(f"CREATE INDEX items_embedding_hnsw ON items USING hnsw (embedding vector_cosine_ops) "
                         f"WITH (m = {M}, ef_construction = {EF_CONSTRUCTION})")
            result.seconds = round(time.perf_counter() - started, 1)
        except psycopg.Error as err:
            result.error = f"{err.sqlstate}: {err.diag.message_primary}"
        finally:
            watcher.stop.set()
            watcher.join()
        result.max_parallel_workers_seen, result.phases_seen = watcher.max_workers, watcher.phases
        if result.error:
            return result
        result.wal_bytes = int(conn.execute("SELECT pg_wal_lsn_diff(pg_current_wal_lsn(), %s)", (wal_before,)).fetchone()[0])
        result.index_bytes = conn.execute("SELECT pg_relation_size('items_embedding_hnsw')").fetchone()[0]
        plan = conn.execute("EXPLAIN SELECT id FROM items ORDER BY embedding <=> %s::vector LIMIT 10",
                            (str(test[0].tolist()),)).fetchall()
        result.plan_uses_index = any("items_embedding_hnsw" in line[0] for line in plan)
        for ef in EF_SEARCH:
            conn.execute(f"SET hnsw.ef_search = {ef}")
            found, started = [], time.perf_counter()
            for q in test:
                rows = conn.execute("SELECT id FROM items ORDER BY embedding <=> %s::vector LIMIT 10",
                                    (str(q.tolist()),)).fetchall()
                found.append([r[0] for r in rows])
            result.query_ms_mean[str(ef)] = round((time.perf_counter() - started) * 1000 / len(test), 2)
            result.recall[str(ef)] = round(recall_at_k(found, truth), 4)
    return result


def main(argv: list[str] | None = None) -> list[dict]:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dsn", required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--experiments", nargs="+", choices=list(EXPERIMENTS), required=True)
    parser.add_argument("--rows", type=int, default=200_000)
    parser.add_argument("--queries", type=int, default=1_000)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    train, test = generate(args.rows, args.queries)
    truth = exact_neighbours(train, test)
    with psycopg.connect(args.dsn, autocommit=True) as conn:
        ensure_table(conn, train)
    results = []
    for name in args.experiments:
        result = build_and_measure(args.dsn, args.label, name, test, truth)
        print(json.dumps(asdict(result)), flush=True)
        results.append(asdict(result))
    existing = json.loads(args.out.read_text()) if args.out.exists() else {"runs": []}
    existing["dataset"] = {"kind": "synthetic Gaussian mixture, see bench/dataset.py", "sha256": fingerprint(train, test),
                           "rows": args.rows, "queries": args.queries, "dimensions": int(train.shape[1]),
                           "m": M, "ef_construction": EF_CONSTRUCTION}
    existing["runs"].extend(results)
    args.out.write_text(json.dumps(existing, indent=2))
    return results


if __name__ == "__main__":
    main()
