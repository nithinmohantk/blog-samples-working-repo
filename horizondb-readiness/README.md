# horizondb-readiness

Sample code for the dataa.dev article *Azure HorizonDB or Azure Database for PostgreSQL Flexible Server: Choosing Azure's PostgreSQL After Ignite 2026* (19 Nov 2026).

| File | What it does |
| :--- | :--- |
| `horizondb_readiness/catalog.py` | What Azure HorizonDB offered at GA: extensions and versions, PostgreSQL major versions, and the capabilities listed as not available, from Microsoft Learn (read 19 Nov 2026) |
| `horizondb_readiness/checks.py` | Rules that turn facts about a source database into blocker / action / info findings |
| `horizondb_readiness/collect.py` | Read-only catalog queries against the source: version, extensions, logical slots, tables without primary keys, connections |
| `horizondb_readiness/__main__.py` | CLI; exit code 0 with no blockers, 2 with blockers, 1 if it cannot connect |
| `vector_filter.py` | Measures how a selective filter starves an HNSW query (rows returned and recall@10 for several `hnsw.ef_search` values) |
| `sample-report.txt`, `vector-filter-output.txt` | Output of the two scripts as printed in the article (local PostgreSQL 16.2) |
| `horizondb-vector-filter-output.txt` | Output of `vector_filter.py` against a real Azure HorizonDB cluster (19 Nov 2026) |

## Run

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m horizondb_readiness "postgresql://user@host:5432/db?sslmode=require" --peak-connections 350
.venv/bin/python -m pytest -q
```

Things SQL cannot see are flags: `--geo-replica`, `--vnet-injection`, `--cmk-geo-backup`, `--retention-days`, `--peak-connections`.

## What was verified on Azure HorizonDB (19 Nov 2026)

A throwaway cluster (PostgreSQL 17.11, Sweden Central, 1 node, 2 vCores, HA disabled) was created in the Azure portal, tested from Azure Cloud Shell and deleted the same evening.

* `CREATE EXTENSION vector` fails until the extension is allow-listed: create a parameter group with `azure.extensions = vector,pg_diskann` (a dynamic parameter) and attach it to the pool with `--param-group-apply Immediate` (took about 2 minutes).
* pgvector 0.8.7 iterative scans fix the starved-result problem: `strict_order` and `relaxed_order` returned 10 of 10 rows on every query. pg_diskann 0.7.6 used a `DiskANNFilteredScan` (filter inside the search) and reached recall@10 1.00 in all three runs. See `horizondb-vector-filter-output.txt`.
* The live server offered 87 extensions with newer versions than the Learn page; `catalog.py` now uses the live list. `max_connections` was 128 on 2 vCores.

## What was verified locally

10 tests pass with Python 3.12, psycopg 3.2.3 and pytest 8.3.3: 6 unit tests of the rules, and 4 live tests against PostgreSQL 16.2 with pgvector 0.6.2 started by `pgserver` 0.1.4 (collector, CLI exit codes and JSON, and the filtered-HNSW measurement). Nothing was run against Azure HorizonDB, which offers PostgreSQL 17 and pgvector 0.8.0; the vector measurement shows the problem pgvector 0.8.0's iterative scans and HorizonDB's filtered DiskANN are meant to address, not those fixes. The catalog is a snapshot: re-read the Microsoft Learn pages before a real migration.
