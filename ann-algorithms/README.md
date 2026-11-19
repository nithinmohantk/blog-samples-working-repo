# ann-algorithms

Companion code for the dataa.dev article *Vector Search Algorithms: Exact Search, IVF, Product Quantization and HNSW* (20 August 2024).

`ann.py` implements, in plain NumPy and for reading rather than production:

- `brute_force`: exact k-nearest-neighbour search, the reference for measuring recall;
- `IVFFlat`: k-means partitions (`nlist`) and a query that scans the `nprobe` nearest partitions;
- `HNSW`: a hierarchical navigable small world graph with `M`, `ef_construction` and query-time `ef`;
- `recall_at_k`.

`example.py` prints recall against work done on synthetic clustered data:

```
IVF  nlist=32 nprobe=1   recall@10=0.875 vectors scanned=114 of 2000
IVF  nlist=32 nprobe=2   recall@10=0.953 vectors scanned=203 of 2000
IVF  nlist=32 nprobe=4   recall@10=0.993 vectors scanned=302 of 2000
IVF  nlist=32 nprobe=8   recall@10=1.000 vectors scanned=577 of 2000
HNSW M=12 ef=10   recall@10=0.978
HNSW M=12 ef=20   recall@10=0.980
HNSW M=12 ef=50   recall@10=0.980
HNSW M=12 ef=100  recall@10=0.980
```

These numbers describe this toy data and these simple implementations; measure your own data with FAISS, hnswlib or your vector database.

## Tests

```bash
pip install numpy==1.26.4 pytest==8.3.2
python -m pytest -q
```

6 tests: exact brute force, IVF exact when every list is probed, IVF recall rising with `nprobe` while scanning under half the data, HNSW recall of at least 0.95 and rising with `ef`, HNSW degree caps and layers, and parameter validation. Tested with Python 3.12.
