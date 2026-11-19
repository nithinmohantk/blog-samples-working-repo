"""Recall against work done, on synthetic clustered data (2,000 x 32, 16 clusters)."""
import numpy as np

from ann import HNSW, IVFFlat, brute_force, recall_at_k

rng = np.random.default_rng(42)
centres = rng.normal(size=(16, 32)) * 4
data = np.vstack([c + rng.normal(size=(125, 32)) for c in centres])
queries = data[rng.choice(len(data), 40, replace=False)] + rng.normal(scale=0.3, size=(40, 32))
truth = [brute_force(data, q, 10) for q in queries]


def recall(search):
    return np.mean([recall_at_k(search(q), t) for q, t in zip(queries, truth)])


ivf = IVFFlat(nlist=32, seed=1).fit(data)
for nprobe in (1, 2, 4, 8):
    scanned = np.mean([ivf.scanned(q, nprobe) for q in queries])
    print(f"IVF  nlist=32 nprobe={nprobe:<3} recall@10={recall(lambda q: ivf.search(q, 10, nprobe)):.3f} "
          f"vectors scanned={scanned:.0f} of {len(data)}")

hnsw = HNSW(M=12, ef_construction=80, seed=3).fit(data)
for ef in (10, 20, 50, 100):
    print(f"HNSW M=12 ef={ef:<4} recall@10={recall(lambda q: hnsw.search(q, 10, ef)):.3f}")
