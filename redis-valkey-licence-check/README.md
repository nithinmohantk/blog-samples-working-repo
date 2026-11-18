# Redis 7.2.4 and Valkey: licence check and compatibility

Sample code for the dataa.dev article *Redis Changes Its Licence, Valkey Forks: What It Means for Your Deployments, and a One-Way Data Trap*.

- `rvcheck/licence.py`: classify a running server (from INFO) or an image reference by licence, as announced on
  20 March 2024: Redis 7.4+ RSALv2/SSPLv1, Redis 7.2.x and earlier BSD-3-Clause, Valkey BSD-3-Clause, Redict LGPL-3.0-only.
- `rvcheck/workload.py`: one redis-py workload across all data types, Lua, Functions and transactions.
- `tools/run_checks.py`: builds on both servers: what they report, the workload, RDB files both ways, replication both ways.
- `ci.sh`: builds Redis 7.2.4 (tag) and Valkey `unstable` at 1950acd (29 March 2024) from source.

Not legal advice.

## What was verified

GitHub Actions ([run](https://github.com/nithinmohantk/blog-samples-working-repo/actions/runs/44418761165)), Python 3.12, redis-py 5.0.3, pytest 8.1.1 (`--exclude-newer 2024-03-29`). All 18 unit tests pass.

```text
== 1. What each server says about itself
Redis 7.2.4: redis_version=7.2.4, redis_git_sha1=d2c8a4b9, redis_mode=standalone, HELLO server=redis, HELLO version=7.2.4, COMMAND COUNT=241
  licence check: Redis 7.2.4: BSD-3-Clause
Valkey unstable: redis_version=255.255.255, redis_git_sha1=1950acd1, redis_mode=standalone, HELLO server=redis, HELLO version=255.255.255, COMMAND COUNT=241
  licence check: Redis-compatible development build 255.255.255: unknown (development branches report 255.255.255; check the source the binary was built from (Redis unstable after 20 March 2024 is RSALv2/SSPLv1, Valkey is BSD-3-Clause))

== 2. The same workload on both (redis-py)
17 checks, 17 identical
digest after workload: redis 71b0efa498711272a034839d1e5228452f5e2b56 valkey 71b0efa498711272a034839d1e5228452f5e2b56

== 3. RDB files
RDB header written by Redis 7.2.4: REDIS0011; by Valkey unstable: REDIS0012
Redis 7.2.4 RDB -> Valkey: started=True, keys=13, same digest=True, functions=['inventory']
Valkey RDB -> Redis 7.2.4: started=False
  log: Redis version=7.2.4, bits=64, commit=d2c8a4b9, modified=0, pid=12505, just started
  log: Can't handle RDB format version 12

== 4. Replication
Valkey replica of Redis 7.2.4: link up
  key written after sync, read on the Valkey replica: 'written on the Redis primary'; digests equal: True
Redis 7.2.4 replica of Valkey: link down after 15 s
  log: Can't handle RDB format version 12
  log: MASTER <-> REPLICA sync started
  log: MASTER <-> REPLICA sync: Flushing old data
  log: MASTER <-> REPLICA sync: Loading DB in memory
  log: MASTER <-> REPLICA sync: receiving streamed RDB from master with EOF to disk
```
