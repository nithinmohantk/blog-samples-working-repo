"""Synthetic vectors and exact ground truth for the benchmark.

The vectors are a seeded Gaussian mixture: cluster centres drawn at random,
points scattered around them with noise about as large as the spread between
centres, so neighbours are neither trivial nor random. Queries come from the
same mixture but are not in the table. Anyone can regenerate the exact same
data from the seed; no download is needed.

Recall measured on this data is for comparing builds with each other (0.5.1
against 0.6.0, serial against parallel). It is not a claim about recall on
real embeddings.
"""
from __future__ import annotations

import hashlib

import numpy as np


def generate(rows: int, queries: int, dim: int = 256, clusters: int = 100,
             noise: float = 0.8, seed: int = 20240203) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    centres = rng.normal(size=(clusters, dim)).astype(np.float32)

    def draw(n: int) -> np.ndarray:
        which = rng.integers(0, clusters, size=n)
        return (centres[which] + noise * rng.normal(size=(n, dim))).astype(np.float32)

    return draw(rows), draw(queries)


def fingerprint(*arrays: np.ndarray) -> str:
    digest = hashlib.sha256()
    for array in arrays:
        digest.update(np.ascontiguousarray(array).tobytes())
    return digest.hexdigest()


def exact_neighbours(train: np.ndarray, test: np.ndarray, k: int = 10, batch: int = 100) -> np.ndarray:
    """Indices of the k nearest training rows by cosine distance, for each query."""
    norms = np.linalg.norm(train, axis=1, keepdims=True)
    unit = train / np.where(norms == 0, 1, norms)
    out = np.empty((len(test), k), dtype=np.int64)
    for start in range(0, len(test), batch):
        q = test[start:start + batch]
        q = q / np.where(np.linalg.norm(q, axis=1, keepdims=True) == 0, 1, np.linalg.norm(q, axis=1, keepdims=True))
        sims = q @ unit.T
        top = np.argpartition(-sims, k, axis=1)[:, :k]
        order = np.take_along_axis(-sims, top, axis=1).argsort(axis=1, kind="stable")
        out[start:start + batch] = np.take_along_axis(top, order, axis=1)
    return out


def recall_at_k(found: list[list[int]], truth: np.ndarray, k: int = 10) -> float:
    hits = sum(len(set(f[:k]) & set(t[:k].tolist())) for f, t in zip(found, truth))
    return hits / (k * len(truth))
