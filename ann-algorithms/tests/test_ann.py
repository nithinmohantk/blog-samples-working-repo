import numpy as np
import pytest

from ann import HNSW, IVFFlat, brute_force, recall_at_k

RNG = np.random.default_rng(42)
# 2,000 vectors in 16 clusters, 32 dimensions: structured like real embeddings, small enough to test fast
CENTRES = RNG.normal(size=(16, 32)) * 4
DATA = np.vstack([c + RNG.normal(size=(125, 32)) for c in CENTRES])
QUERIES = DATA[RNG.choice(len(DATA), 40, replace=False)] + RNG.normal(scale=0.3, size=(40, 32))
K = 10


def mean_recall(search):
    return np.mean([recall_at_k(search(q), brute_force(DATA, q, K)) for q in QUERIES])


def test_brute_force_is_exact_and_sorted():
    q = QUERIES[0]
    idx = brute_force(DATA, q, K)
    d = ((DATA - q) ** 2).sum(1)
    assert list(idx) == list(np.argsort(d)[:K])


@pytest.fixture(scope="module")
def ivf():
    return IVFFlat(nlist=32, seed=1).fit(DATA)


def test_ivf_probing_every_list_is_exact(ivf):
    assert mean_recall(lambda q: ivf.search(q, K, nprobe=32)) == 1.0


def test_ivf_recall_rises_with_nprobe_and_scans_less_than_everything(ivf):
    r1 = mean_recall(lambda q: ivf.search(q, K, nprobe=1))
    r4 = mean_recall(lambda q: ivf.search(q, K, nprobe=4))
    assert r4 >= r1 and r4 >= 0.9
    assert np.mean([ivf.scanned(q, 4) for q in QUERIES]) < 0.5 * len(DATA)


@pytest.fixture(scope="module")
def hnsw():
    return HNSW(M=12, ef_construction=80, seed=3).fit(DATA)


def test_hnsw_recall_is_high_and_rises_with_ef(hnsw):
    low = mean_recall(lambda q: hnsw.search(q, K, ef=10))
    high = mean_recall(lambda q: hnsw.search(q, K, ef=100))
    assert high >= low and high >= 0.95


def test_hnsw_graph_respects_degree_caps(hnsw):
    assert max(len(v) for v in hnsw.graph[0].values()) <= 2 * hnsw.M
    for layer in hnsw.graph[1:]:
        assert max((len(v) for v in layer.values()), default=0) <= hnsw.M
    assert len(hnsw.graph) > 1                       # upper layers exist


def test_invalid_parameters():
    with pytest.raises(ValueError):
        IVFFlat(nlist=10).fit(DATA[:5])
    with pytest.raises(ValueError):
        HNSW(M=1)
    assert HNSW().search(DATA[0], 3).size == 0
