# PostgreSQL 19, tried beside 18

Sample for the article [PostgreSQL 19: REPACK, WAIT FOR LSN and ON CONFLICT DO SELECT, Tested Against 18](https://www.dataa.dev/2026/11/23/postgresql-19-repack-wait-for-lsn-on-conflict-do-select-tested/).

It starts three servers in Docker and puts the same questions to two versions:

| Server | Port | Role |
| :--- | :--- | :--- |
| `postgres:19` | 5419 | primary |
| `postgres:19` | 5420 | streaming standby of the primary, with a replication slot |
| `postgres:18` | 5418 | comparison |

## Run it

Needs Docker and Python 3.12 or later.

```bash
./ci.sh out
cat out/results.txt
```

The password in `ci.sh` is a throwaway for containers that live for one run. All data is generated.

## What is in it

| File | What it does |
| :--- | :--- |
| `ci.sh` | Starts the servers, builds the standby with `pg_basebackup`, runs everything, removes the containers |
| `lab/run.py` | Eleven experiments; writes `results.txt` |
| `sql/tour.sql` | The new statements in plain SQL; run with `psql -a`, output in `03-tour.txt` |
| `sql/upgrade-checks.sql` | Eight checks to run on a server before it goes to 19 |
| `sql/upgrade-plant.sql` | Puts one of everything those checks look for onto the 18 container |

The experiments: changed defaults; logical decoding at `wal_level = replica`; `REPACK` and `REPACK (CONCURRENTLY)` against `VACUUM FULL` with a writer and a reader on the table; `INSERT ... ON CONFLICT DO SELECT`; `WAIT FOR LSN` on the standby; `IGNORE NULLS`, `COPY ... (FORMAT json)`, `random(date, date)` and jsonpath string methods; `NOT IN` and aggregation before a join; bulk insert with a foreign key; `pg_plan_advice` and `pg_stash_advice`; pglz against lz4; the new statistics views.

## What has been verified

[GitHub Actions run 45189048112](https://github.com/nithinmohantk/blog-samples-working-repo/actions/runs/45189048112) on commit `e0765b8`, 23 November 2026, PostgreSQL 19.0 and 18.7: all eleven experiments, the tour and the eight upgrade checks completed without error. The output is on the `ci-results-postgresql-19-first-look` branch.

Not verified: `pg_upgrade` was not run. `REPACK (CONCURRENTLY)` was not tried on partitioned or unlogged tables, under a long-running snapshot, or with a failure part way. The timings compare two versions on one hosted runner and vary between runs; they are not a benchmark.
