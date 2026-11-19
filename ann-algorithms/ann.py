"""Three nearest-neighbour search algorithms in plain NumPy, for reading.

- `brute_force`: exact search; the reference every approximate index is
  measured against.
- `IVFFlat`: inverted file index. k-means splits the vectors into `nlist`
  clusters; a query scans only the `nprobe` closest clusters.
- `HNSW`: hierarchical navigable small world graph (Malkov and Yashunin).
  A query descends sparse upper layers greedily, then searches the dense
  bottom layer with a candidate list of size `ef`.
- `recall_at_k`: the share of the true k nearest neighbours an index returns.

Distances are squared Euclidean. For cosine similarity, normalise vectors to
unit length first; the ranking is then the same. Production libraries (FAISS,
hnswlib, the engines inside vector databases) are far faster; these versions
exist to make the parameters understandable.
"""
from __future__ import annotations

import heapq
import math

import numpy as np


def _sqdist(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return ((a - b) ** 2).sum(axis=-1)


def brute_force(data: np.ndarray, query: np.ndarray, k: int) -> np.ndarray:
    d = _sqdist(data, query)
    idx = np.argpartition(d, min(k, len(d) - 1))[:k]
    return idx[np.argsort(d[idx])]


def recall_at_k(found: np.ndarray, truth: np.ndarray) -> float:
    return len(set(found.tolist()) & set(truth.tolist())) / len(truth)


class IVFFlat:
    def __init__(self, nlist: int, iterations: int = 20, seed: int = 0):
        self.nlist, self.iterations = nlist, iterations
        self.rng = np.random.default_rng(seed)

    def fit(self, data: np.ndarray) -> "IVFFlat":
        if self.nlist > len(data):
            raise ValueError("nlist cannot exceed the number of vectors")
        self.data = data
        centroids = data[self.rng.choice(len(data), self.nlist, replace=False)].copy()
        for _ in range(self.iterations):                       # Lloyd's k-means
            assign = np.argmin(((data[:, None, :] - centroids[None, :, :]) ** 2).sum(-1), axis=1)
            for c in range(self.nlist):
                members = data[assign == c]
                if len(members):
                    centroids[c] = members.mean(axis=0)
        self.centroids = centroids
        self.lists = [np.flatnonzero(assign == c) for c in range(self.nlist)]
        return self

    def search(self, query: np.ndarray, k: int, nprobe: int = 1) -> np.ndarray:
        probe = np.argsort(_sqdist(self.centroids, query))[:nprobe]
        cand = np.concatenate([self.lists[c] for c in probe])
        if len(cand) == 0:
            return cand
        order = np.argsort(_sqdist(self.data[cand], query))[:k]
        return cand[order]

    def scanned(self, query: np.ndarray, nprobe: int) -> int:
        probe = np.argsort(_sqdist(self.centroids, query))[:nprobe]
        return int(sum(len(self.lists[c]) for c in probe))


class HNSW:
    def __init__(self, M: int = 16, ef_construction: int = 100, seed: int = 0):
        if M < 2:
            raise ValueError("M must be at least 2")
        self.M, self.M0, self.efc = M, 2 * M, ef_construction
        self.mL = 1 / math.log(M)
        self.rng = np.random.default_rng(seed)
        self.vectors: list[np.ndarray] = []
        self.graph: list[dict[int, list[int]]] = []    # graph[layer][node] -> neighbours
        self.entry: int | None = None
        self.top = -1

    def _d(self, i: int, q: np.ndarray) -> float:
        return float(((self.vectors[i] - q) ** 2).sum())

    def _search_layer(self, q: np.ndarray, entries: list[int], ef: int, layer: int) -> list[tuple[float, int]]:
        visited = set(entries)
        cand = [(self._d(e, q), e) for e in entries]
        heapq.heapify(cand)                                    # closest first
        best = [(-d, e) for d, e in cand]                      # farthest first (max-heap)
        heapq.heapify(best)
        while cand:
            d, c = heapq.heappop(cand)
            if d > -best[0][0] and len(best) >= ef:
                break
            for n in self.graph[layer].get(c, []):
                if n in visited:
                    continue
                visited.add(n)
                dn = self._d(n, q)
                if len(best) < ef or dn < -best[0][0]:
                    heapq.heappush(cand, (dn, n))
                    heapq.heappush(best, (-dn, n))
                    if len(best) > ef:
                        heapq.heappop(best)
        return sorted((-d, e) for d, e in best)

    def add(self, v: np.ndarray) -> int:
        node = len(self.vectors)
        self.vectors.append(np.asarray(v, dtype=float))
        level = int(-math.log(1.0 - self.rng.random()) * self.mL)
        while len(self.graph) <= level:
            self.graph.append({})
        for layer in range(level + 1):
            self.graph[layer][node] = []
        if self.entry is None:
            self.entry, self.top = node, level
            return node
        ep = [self.entry]
        for layer in range(self.top, level, -1):              # greedy descent
            ep = [self._search_layer(v, ep, 1, layer)[0][1]]
        for layer in range(min(level, self.top), -1, -1):
            found = self._search_layer(v, ep, self.efc, layer)
            cap = self.M0 if layer == 0 else self.M
            neighbours = [e for _, e in found[: self.M]]
            self.graph[layer][node] = neighbours
            for n in neighbours:                               # connect both ways, then prune
                links = self.graph[layer][n]
                links.append(node)
                if len(links) > cap:
                    links.sort(key=lambda x: self._d(x, self.vectors[n]))
                    del links[cap:]
            ep = [e for _, e in found]
        if level > self.top:
            self.entry, self.top = node, level
        return node

    def fit(self, data: np.ndarray) -> "HNSW":
        for v in data:
            self.add(v)
        return self

    def search(self, q: np.ndarray, k: int, ef: int = 50) -> np.ndarray:
        if self.entry is None:
            return np.array([], dtype=int)
        ep = [self.entry]
        for layer in range(self.top, 0, -1):
            ep = [self._search_layer(q, ep, 1, layer)[0][1]]
        found = self._search_layer(q, ep, max(ef, k), 0)
        return np.array([e for _, e in found[:k]])
