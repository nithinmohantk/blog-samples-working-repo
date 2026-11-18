import os
import struct
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bench"))
from dataset import exact_neighbours, fingerprint, generate, recall_at_k  # noqa: E402
from run import binary_copy  # noqa: E402


def brute_force(train, test, k):
    def unit(a):
        return a / np.linalg.norm(a, axis=1, keepdims=True)
    return np.argsort(-(unit(test) @ unit(train).T), axis=1, kind="stable")[:, :k]


def test_exact_neighbours_match_brute_force():
    rng = np.random.default_rng(7)
    train = rng.normal(size=(500, 16)).astype(np.float32)
    test = rng.normal(size=(20, 16)).astype(np.float32)
    assert (exact_neighbours(train, test, k=10, batch=7) == brute_force(train, test, 10)).all()


def test_cosine_ignores_vector_length():
    rng = np.random.default_rng(1)
    train = rng.normal(size=(200, 8)).astype(np.float32)
    test = rng.normal(size=(5, 8)).astype(np.float32)
    scaled = train * rng.uniform(0.1, 10, size=(200, 1)).astype(np.float32)
    assert (exact_neighbours(train, test) == exact_neighbours(scaled, test)).all()


def test_recall_counts_overlap_not_order():
    truth = np.array([[1, 2, 3], [4, 5, 6]])
    assert recall_at_k([[3, 2, 1], [4, 9, 9]], truth, k=3) == pytest.approx(4 / 6)


def test_binary_copy_layout():
    vectors = np.array([[1.5, -2.0, 0.25]], dtype=np.float32)
    data = binary_copy(vectors)
    assert data.startswith(b"PGCOPY\n\xff\r\n\x00")
    body = data[19:-2]
    fields, id_len, row_id, vec_len, dim, unused = struct.unpack(">hiiihh", body[:18])
    assert (fields, id_len, row_id, vec_len, dim, unused) == (2, 4, 0, 16, 3, 0)
    assert struct.unpack(">3f", body[18:]) == (1.5, -2.0, 0.25)
    assert data.endswith(struct.pack(">h", -1))


@pytest.mark.skipif("PGVECTOR_DSN" not in os.environ, reason="needs a Postgres with pgvector")
def test_binary_copy_round_trips_through_pgvector():
    import psycopg
    vectors = np.random.default_rng(3).normal(size=(50, 32)).astype(np.float32)
    with psycopg.connect(os.environ["PGVECTOR_DSN"], autocommit=True) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        conn.execute("DROP TABLE IF EXISTS copy_check")
        conn.execute("CREATE TEMP TABLE copy_check (id int4, embedding vector(32))")
        with conn.cursor().copy("COPY copy_check (id, embedding) FROM STDIN WITH (FORMAT binary)") as copy:
            copy.write(binary_copy(vectors))
        rows = conn.execute("SELECT id, embedding::text FROM copy_check ORDER BY id").fetchall()
    assert [r[0] for r in rows] == list(range(50))
    loaded = np.array([[float(x) for x in r[1].strip("[]").split(",")] for r in rows], dtype=np.float32)
    assert (loaded == vectors).all()


def test_generated_data_is_reproducible_and_clustered():
    a_train, a_test = generate(2_000, 50, dim=32, clusters=10)
    b_train, b_test = generate(2_000, 50, dim=32, clusters=10)
    assert fingerprint(a_train, a_test) == fingerprint(b_train, b_test)
    truth = exact_neighbours(a_train, a_test, k=10)
    # Nearest neighbours should be much closer than a random row.
    unit = a_train / np.linalg.norm(a_train, axis=1, keepdims=True)
    q = a_test / np.linalg.norm(a_test, axis=1, keepdims=True)
    near = np.mean([q[i] @ unit[truth[i, 0]] for i in range(len(q))])
    rand = np.mean(q @ unit[:50].T)
    assert near > rand + 0.3
