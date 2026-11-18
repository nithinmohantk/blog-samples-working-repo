# pgvector 0.6.0: parallel HNSW index builds

Sample code for the dataa.dev article *pgvector 0.6.0 Parallel HNSW Builds: What Speeds Up, and the Docker /dev/shm Trap*.

Builds pgvector 0.5.1 and 0.6.0 from their git tags on `postgres:16.1-bookworm`, then builds the same HNSW
index under different settings and measures each build: time, parallel workers actually launched, notices,
WAL written, index size, and recall@10 at two `ef_search` values.

## What is here

| Path | What it does |
| --- | --- |
| `docker/Dockerfile` | pgvector from a git tag on a fixed Postgres image, built like pgvector's own Dockerfile (`make OPTFLAGS=""`). |
| `bench/dataset.py` | Seeded synthetic data (Gaussian mixture, 256 dimensions) and exact cosine ground truth with numpy. |
| `bench/run.py` | Loads the table with binary COPY, runs the experiments, watches `pg_stat_activity` during each build. |
| `bench/report.py` | Prints the results as a table. |
| `tests/` | Ground truth against brute force, recall maths, the binary COPY layout, and a round trip through a real pgvector. |
| `ci.sh` | What CI runs: builds both images, runs three containers (0.5.1 and 0.6.0 with 2 GB `/dev/shm`, 0.6.0 with Docker's default 64 MB). |

## Run it

```bash
pip install uv
uv pip install --exclude-newer 2024-02-02 "psycopg[binary]" numpy h5py pytest
./ci.sh out        # needs Docker; about 20 minutes on a 4 vCPU machine
```

## What was verified

GitHub Actions, 4 vCPU and 15 GiB RAM, Python 3.12 with psycopg 3.1.17, numpy 1.26.3, pytest 8.0.0.
200,000 vectors, 1,000 queries, `m = 16`, `ef_construction = 64`, cosine:

```text
container      experiment             mem   workers  seen  build s  WAL MB  index MB  recall ef40  recall ef100  outcome
0.5.1 shm-2g   default-mem            64MB  3        0     406.0    649     260       0.829        0.931         graph spilled to disk
0.5.1 shm-2g   serial-1gb             1GB   0        0     123.2    304     260       0.836        0.944         in memory
0.5.1 shm-2g   parallel-1gb           1GB   3        0     120.1    304     260       0.843        0.942         in memory
0.6.0 shm-2g   default-mem            64MB  3        3     139.1    254     260       0.836        0.931         graph spilled to disk
0.6.0 shm-2g   serial-1gb             1GB   0        0     85.0     254     260       0.837        0.936         in memory
0.6.0 shm-2g   parallel-1gb           1GB   3        3     30.5     254     260       0.840        0.939         in memory
0.6.0 shm-2g   parallel-1gb           1GB   3        3     31.1     254     260       0.844        0.943         in memory
0.6.0 shm-2g   serial-1gb             1GB   0        0     85.1     254     260       0.832        0.925         in memory
0.6.0 shm-2g   parallel-1gb-unlogged  1GB   3        3     30.2     0       260       0.818        0.920         in memory
0.6.0 shm-64m  parallel-1gb           1GB   3        0     -        -       -         -            -             53100: could not resize shared memory segment "/PostgreSQL.2470067724" to 1070648768 bytes: No space left on device
0.6.0 shm-64m  default-workers-1gb    1GB   2        0     -        -       -         -            -             53100: could not resize shared memory segment "/PostgreSQL.3254711394" to 1070632320 bytes: No space left on device
0.6.0 shm-64m  serial-1gb             1GB   0        0     83.1     254     260       0.839        0.940         in memory
```

- 0.5.1 never launched parallel workers for HNSW, whatever `max_parallel_maintenance_workers` said.
- With Docker's default 64 MB `/dev/shm`, a parallel 0.6.0 build with `maintenance_work_mem = 1GB` fails with
  error 53100, both with 3 workers requested and with the setting left at its default of 2. It does not fall
  back to a serial build. A serial build in the same container works.
- Recall differences between builds are within the variation between two runs of the same build.

## What was not verified

- The data is synthetic. Recall is only compared between builds; it says nothing about recall on real embeddings.
  The ann-benchmarks NYTimes file was the first choice, but the download was refused from the CI runner.
- One machine size (4 vCPU). More cores and larger tables will give different ratios.
- No managed Postgres service was tested.
