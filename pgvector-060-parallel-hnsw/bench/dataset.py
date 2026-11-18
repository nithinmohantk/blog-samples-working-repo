"""Vectors and exact ground truth for the benchmark.

Uses the ann-benchmarks nytimes-256-angular file (256-dimension, cosine).
The first `rows` training vectors are the table; the first `queries` test
vectors are the queries. Ground truth is recomputed exactly for that subset,
because the file's own neighbours refer to the full training set.
"""
from __future__ import annotations

import hashlib
import urllib.request
from pathlib import Path

import h5py
import numpy as np

URL = "http://ann-benchmarks.com/nytimes-256-angular.hdf5"


def download(dest: Path, url: str = URL) -> Path:
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(".part")
        urllib.request.urlretrieve(url, tmp)
        tmp.rename(dest)
    return dest


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load(path: Path, rows: int, queries: int) -> tuple[np.ndarray, np.ndarray]:
    with h5py.File(path, "r") as f:
        train = np.asarray(f["train"][:rows], dtype=np.float32)
        test = np.asarray(f["test"][:queries], dtype=np.float32)
    return train, test


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
