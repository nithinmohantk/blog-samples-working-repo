# Redis Changes Its Licence, Valkey Forks: What It Means for Your Deployments, and a One-Way Data Trap

*Saturday 30 March 2024. Slug `redis-licence-change-valkey-fork-deployments-rdb-rollback`*

**Excerpt:** Redis 7.4 moves to RSALv2/SSPLv1 and Valkey forks 7.2.4. An inventory tool, why INFO cannot tell the forks apart, and tests showing Redis 7.2.4 data moves to Valkey cleanly but Valkey's development line writes an RDB format Redis 7.2.4 cannot read.

On 20 March 2024 Redis Ltd. announced that Redis would no longer be released under the three-clause BSD licence. Starting with Redis 7.4, the server is dual-licensed under the Redis Source Available License v2 and the Server Side Public License v1, neither of which is an OSI-approved open source licence. Eight days later, on 28 March, the Linux Foundation announced Valkey, a fork that continues from Redis 7.2.4 under BSD, with AWS, Google Cloud, Oracle, Ericsson and Snap among its supporters.

For most teams the immediate question is not philosophical. It is which of their Redis deployments are affected, whether anything needs to happen now, and whether a move to a fork is safe. This article answers those questions with a small inventory tool and with tests run on both servers built from source: Redis 7.2.4, the last BSD release, and Valkey as it stood on 29 March, before it had made a release of its own.

## What actually changed

The change applies to future releases, not to code already published. Redis 7.2.x and everything before it stay BSD-licensed, and Redis has said security fixes will continue to be backported to those versions under BSD. What changes is what you can do with Redis 7.4 and later:

| Licence | What it allows and limits |
| :--- | :--- |
| BSD-3-Clause (Redis up to 7.2.x, Valkey) | Use, modify, redistribute and offer as a service without conditions beyond keeping the notice |
| RSALv2 (Redis 7.4 and later) | Use, copy, modify and distribute, but with limits on commercialising the software, including offering it to others as a managed service |
| SSPLv1 (Redis 7.4 and later, alternative) | Copyleft; offering the software as a service requires publishing the source of the whole service stack under the SSPL |
| LGPL-3.0-only (Redict changes) | Copyleft on the library itself; Redict is a separate fork announced on 22 March |

Redis says the change does not affect people who use Redis inside their own applications, third-party client libraries, or existing commercial customers. The target is cloud providers selling Redis as a service. For a company that runs Redis behind its own product, the practical impact is smaller than the headlines suggest, but not zero: distributions may drop or replace the package, container tags will move to 7.4 when it ships, and procurement and open source policies often forbid non-OSI licences regardless of how they would apply.

![Six cards showing what the Redis licence change means for internal self-hosted use, ElastiCache customers, companies selling Redis as a service, floating image tags, distribution packages and the Valkey and Redict forks](img1.jpg)
*The impact depends on how you run Redis, not on the fact that you run it.*

## What applies to ElastiCache

Amazon ElastiCache customers do not hold the licence obligation; AWS does, as the provider. On 30 March the newest ElastiCache engine is Redis 7.1, released in November 2023 and also used by ElastiCache Serverless, and it is built from code that predates the change. AWS is one of Valkey's founding supporters, with an AWS principal engineer among its creators, but it has not said what future ElastiCache engines will be. There is nothing for ElastiCache customers to do this week except note that the engine roadmap now depends on a decision AWS has not yet announced.

## Finding your deployments

An inventory has two sources: running servers, which can be asked what they are, and image references in registries, Helm values and Compose files, which can be read without connecting to anything. Both are covered by the sample. For running servers, the INFO command is the obvious source:

```python
def classify(info: dict) -> Licence:
    """`info` is the parsed INFO SERVER section (redis-py's client.info('server'))."""
    if str(info.get("server_name", "")).lower() == "valkey" or "valkey_version" in info:
        return Licence("Valkey", str(info.get("valkey_version", info.get("redis_version"))), "BSD-3-Clause")
    if "redict_version" in info:
        return Licence("Redict", str(info["redict_version"]), "LGPL-3.0-only (changes); BSD-3-Clause (inherited code)")
    raw = str(info.get("redis_version", ""))
    v = _version(raw)
    if v == UNSTABLE:
        return Licence("Redis-compatible development build", raw, "unknown",
                       "development branches report 255.255.255; check the source the binary was built from "
                       "(Redis unstable after 20 March 2024 is RSALv2/SSPLv1, Valkey is BSD-3-Clause)")
    if not v:
        return Licence("unknown", raw, "unknown")
    if v >= (7, 4):
        return Licence("Redis", raw, "RSALv2 or SSPLv1")
    return Licence("Redis", raw, "BSD-3-Clause")
```

This is what the two servers said about themselves in the test run:

```text
Redis 7.2.4: redis_version=7.2.4, redis_git_sha1=d2c8a4b9, redis_mode=standalone, HELLO server=redis, HELLO version=7.2.4, COMMAND COUNT=241
  licence check: Redis 7.2.4: BSD-3-Clause
Valkey unstable: redis_version=255.255.255, redis_git_sha1=1950acd1, redis_mode=standalone, HELLO server=redis, HELLO version=255.255.255, COMMAND COUNT=241
  licence check: Redis-compatible development build 255.255.255: unknown (development branches report 255.255.255; check the source the binary was built from (Redis unstable after 20 March 2024 is RSALv2/SSPLv1, Valkey is BSD-3-Clause))
```

Valkey on 29 March already builds a binary called `valkey-server`, but everything a client can see still says Redis: `redis_version` is `255.255.255`, the value every Redis development build reports, and `HELLO` returns `server=redis`. A licence check that relies on the server's own answer cannot tell a Valkey build from a Redis development build taken after 20 March, so the classifier returns unknown rather than guessing. Until the forks add their own identifiers, the binary's source and build record are the only reliable evidence. That is an argument for recording the source commit of every server build you deploy.

For image references, the tag carries the version, with one trap:

```python
def classify_image_tag(image: str) -> Licence:
    """For inventories that only have image references, e.g. from a registry or a Helm values file."""
    name, _, tag = image.rpartition(":") if ":" in image.split("/")[-1] else (image, "", "latest")
    base = name.split("/")[-1]
    if base == "valkey":
        return Licence("Valkey", tag, "BSD-3-Clause")
    if base == "redict":
        return Licence("Redict", tag, "LGPL-3.0-only (changes); BSD-3-Clause (inherited code)")
    if base == "redis":
        v = _version(tag.split("-")[0])
        if not v or tag in ("latest", "alpine", "bookworm"):
            return Licence("Redis", tag, "unknown", "floating tag: pin a version, it will move to 7.4")
        return classify({"redis_version": ".".join(map(str, v))})
    return Licence("not Redis", tag, "n/a")
```

Floating tags such as `redis:latest` and `redis:alpine` are the real risk. They are correct today and will point at Redis 7.4 on the day it is published, changing the licence of a deployment without any change in your repositories. Pinning exact versions is the first concrete action for most teams, and it is worth doing whatever you decide about forks.

## Test setup

Valkey had no release on 30 March; its repository held a `7.2` branch at exactly the Redis 7.2.4 commit and an `unstable` branch carried over from Redis's development branch. The tests build Redis 7.2.4 from its tag and Valkey's `unstable` branch at its last commit of 29 March, then run four checks with redis-py 5.0.3, the client release current at the time:

```bash
REDIS_TAG=7.2.4                                            # 9 January 2024, the last BSD-3-Clause release
VALKEY_SHA=1950acd1e2b8c2282d51e528377f6e564eb447cd       # valkey unstable, 29 March 2024; no release existed yet

build() {  # build <name> <repo url> <ref>
  local dir="$work/$1"
  rm -rf "$dir" && mkdir -p "$dir" && cd "$dir"
  git init -q && git remote add origin "$2" && git fetch -q --depth 1 origin "$3" && git checkout -q FETCH_HEAD
  make -j"$(nproc)" BUILD_TLS=no > "$work/$1-build.log" 2>&1 || { tail -30 "$work/$1-build.log"; return 1; }
  cd - > /dev/null
}

echo "== unit tests"
```

Each server is started from a fresh directory, optionally with an RDB file copied in, so the same helper covers normal start-up, loading the other server's snapshot, and replication:

```python
def start(binary: Path, port: int, name: str, rdb: Path | None = None) -> redis.Redis:
    d = WORK / name
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True)
    if rdb:
        shutil.copy(rdb, d / "dump.rdb")
    subprocess.run([str(binary), "--port", str(port), "--dir", str(d), "--dbfilename", "dump.rdb",
                    "--save", "", "--appendonly", "no", "--enable-debug-command", "yes",
                    "--daemonize", "yes", "--logfile", str(d / "server.log")], check=True)
    r = redis.Redis(port=port, decode_responses=True)
    for _ in range(100):
        try:
            if r.ping():
                return r
        except redis.ConnectionError:
            time.sleep(0.1)
        except redis.BusyLoadingError:
            time.sleep(0.1)
    return r
```

## Results: commands and data

The workload covers strings, hashes, lists, sets, sorted sets, streams with consumer groups, HyperLogLog, bitmaps, geospatial commands, a Lua script, a Redis Functions library with an error path, a transaction, object encodings and the expiry options added in Redis 7.0. Every result was compared value by value, and the whole dataset was compared with `DEBUG DIGEST`:

```text
17 checks, 17 identical
digest after workload: redis 71b0efa498711272a034839d1e5228452f5e2b56 valkey 71b0efa498711272a034839d1e5228452f5e2b56
```

No differences, which is expected: Valkey had changed names and documentation, not behaviour. Both servers also reported the same 241 commands, and the client needed no change at all: the workload used an unmodified redis-py 5.0.3 against both. One client-side detail is worth checking in your own tooling. Libraries and scripts that compare `redis_version` to decide which features to use will read 255.255.255 as newer than any release, which is right for a development build but may enable code paths the server does not support. The interesting results are in the data files.

## Results: RDB files and replication

```text
RDB header written by Redis 7.2.4: REDIS0011; by Valkey unstable: REDIS0012
Redis 7.2.4 RDB -> Valkey: started=True, keys=13, same digest=True, functions=['inventory']
Valkey RDB -> Redis 7.2.4: started=False
  log: Redis version=7.2.4, bits=64, commit=d2c8a4b9, modified=0, pid=12505, just started
  log: Can't handle RDB format version 12
```

```text
Valkey replica of Redis 7.2.4: link up
  key written after sync, read on the Valkey replica: 'written on the Redis primary'; digests equal: True
Redis 7.2.4 replica of Valkey: link down after 15 s
  log: Can't handle RDB format version 12
  log: MASTER <-> REPLICA sync started
  log: MASTER <-> REPLICA sync: Flushing old data
  log: MASTER <-> REPLICA sync: Loading DB in memory
  log: MASTER <-> REPLICA sync: receiving streamed RDB from master with EOF to disk
```

![Diagram of migration paths between Redis 7.2.4 and Valkey unstable: Redis RDB files load into Valkey and a Valkey replica syncs from Redis, but Valkey writes RDB format version 12, which Redis 7.2.4 cannot load, so the reverse paths fail](img2.jpg)
*Moving to Valkey's development line is one-way.*

Moving data from Redis 7.2.4 to Valkey works both ways you would try: the snapshot loads with all keys and the Functions library, and a Valkey replica syncs from a Redis primary and keeps up with new writes. Moving back does not. Valkey's development branch writes RDB format version 12, and Redis 7.2.4 refuses it, both from a file and over replication, where the replica connects and receives the snapshot, then fails to load it and the link stays down.

This is not something Valkey introduced. Redis's own development branch moved to RDB version 12 in October 2023, five months before the licence change, and Valkey's `unstable` branch inherited it. The practical rule is about lines, not projects: a server on the 7.2 line writes version 11 and can be rolled back to Redis 7.2.4; a server on the newer line, from either project, cannot. Any migration plan needs to say which line it targets and accept that the rollback path closes once the first snapshot is written in the new format.

## The options on 30 March

| Option | Licence | State on 30 March 2024 | Main trade-off |
| :--- | :--- | :--- | :--- |
| Stay on Redis 7.2.x | BSD-3-Clause | Released; security fixes promised | No new features; eventually unsupported |
| Move to Redis 7.4 when released | RSALv2 or SSPLv1 | Not yet released | Fine for internal use; check redistribution and service use |
| Valkey | BSD-3-Clause | Announced 28 March; no release yet | Broad backing, but no release history to judge yet |
| Redict | LGPL-3.0-only for changes | 7.3.0 release candidate on 26 March | Small independent project; copyleft on changes |

The fork that matters most for AWS users is Valkey, because AWS is among its backers and the team includes a long-time Redis core maintainer. But a fork announced two days ago is a plan, not a product. Its first releases, its compatibility promises and its support from distributions and managed services will decide whether it becomes the default. For most teams, the sensible position this week is to pin to 7.2.x, take the inventory, and run their own workload against Valkey in staging, so the decision can be made on evidence when the first releases arrive.

## Planning a cut-over with replication

When the time comes, replication gives a cut-over that is a failover rather than a restore, and the test above shows the mechanics already work from Redis 7.2.4 to Valkey:

- **Add the new server as a replica.** Point it at the current Redis primary with REPLICAOF and wait for `master_link_status:up`.
- **Prove the data matches.** Compare `DEBUG DIGEST` on both, or sample keys, while writes continue.
- **Take a snapshot on the old primary.** This is the rollback point, in a format Redis 7.2.4 can load.
- **Pause writes and promote.** Stop writes briefly, check replication offsets match, run REPLICAOF NO ONE on the new server and move clients to it.
- **Keep the old server until confidence is high.** If the new server writes RDB version 12, the rollback snapshot is the only way back.

Three things need separate checks. Sentinel and cluster mode add their own configuration and failover behaviour, which the standalone test here does not cover. Modules from Redis Stack, such as search and JSON, were already under RSALv2 or SSPLv1 before this week and are not part of either fork, so workloads that depend on them need a separate plan. And configuration files, ACL files and monitoring that match on process names or the word redis will need reviewing as the forks rename things.

## What to do now

- **Pin versions.** Replace floating Redis tags with exact versions in every chart, Compose file and Dockerfile. Redis 7.2.4 is BSD and will receive backported security fixes.
- **Take an inventory.** List every Redis server and image reference with its version and how it is used: internal, embedded in a product you ship, or offered to others as a service.
- **Check how you use it.** Internal use is unaffected by the new terms. Redistribution in a product and managed-service offerings need a closer reading of RSALv2 and SSPLv1, ideally with your legal team.
- **Record build provenance.** The server's own version string does not identify the project; the source commit does.
- **Test a fork in staging, not production.** Valkey had no release on 30 March. Run your workload against it, and test the move with replication so cut-over is a failover rather than a restore.
- **Plan the rollback before the move.** Stay on the 7.2 line if you need to be able to go back to Redis 7.2.4; keep a Redis-format snapshot taken before cut-over.
- **Watch the package sources.** Fedora and openSUSE are already discussing dropping Redis, so the package your hosts install may change.

## Decision framework

| Situation | Recommendation |
| :--- | :--- |
| Self-hosted Redis for your own applications | Pin 7.2.x; no licence action; evaluate Valkey once it publishes releases |
| Redis bundled in a product you ship to customers | Review RSALv2 and SSPLv1 before adopting 7.4; plan for a BSD fork or 7.2.x |
| Redis offered to others as a managed service | 7.4 needs an agreement with Redis or a move to a fork |
| ElastiCache | No action; watch AWS's engine announcements |
| Floating image tags | Pin now, whatever else you decide |
| Planning a move to Valkey | Use replication for cut-over; target the 7.2 line if rollback to Redis 7.2.4 matters |

> **NOT LEGAL ADVICE**  
> The licence summaries here follow Redis's announcement and FAQ of 20 March 2024. How RSALv2 and SSPLv1 apply to a particular product or service depends on details that only the licence texts and your own lawyers can settle.

> **HOW THIS WAS CHECKED**  
> The sample ran in GitHub Actions ([run](https://github.com/nithinmohantk/blog-samples-working-repo/actions/runs/44418761165)) on Python 3.12 with redis-py 5.0.3 and pytest 8.1.1 (packages as of 29 March 2024). Redis was built from tag 7.2.4 (commit d2c8a4b9) and Valkey from its `unstable` branch at commit 1950acd, the last commit of 29 March 2024. All 18 unit tests passed and the output above is copied from that run. The RDB version history comes from the Redis repository's `src/rdb.h`. Nothing was run against ElastiCache.

## Key takeaways

- Redis 7.4 and later are RSALv2 or SSPLv1; Redis 7.2.x and earlier remain BSD with security fixes backported.
- Internal use is unaffected; redistribution and managed-service offerings are where the new terms bite.
- Floating tags such as redis:latest will change licence on the day 7.4 ships; pin versions now.
- A server's INFO output cannot tell Valkey's development build from Redis's; record build provenance.
- Redis 7.2.4 data moves to Valkey cleanly, but Valkey's development line writes RDB version 12, which Redis 7.2.4 cannot read, so plan the rollback first.

If you have already started moving a Redis estate, let me know in the comments below which route you took.

> **GET THE CODE**  
> [https://github.com/nithinmohantk/blog-samples-working-repo/tree/main/redis-valkey-licence-check](https://github.com/nithinmohantk/blog-samples-working-repo/tree/main/redis-valkey-licence-check)

## Glossary

- **BSD-3-Clause**: A permissive open source licence; Redis used it until 7.2.x, Valkey keeps it.
- **RSALv2**: Redis Source Available License v2: source-available, with limits on commercialising the software.
- **SSPLv1**: Server Side Public License v1: copyleft that extends to the whole stack of a service offering the software.
- **OSI**: Open Source Initiative, which maintains the list of approved open source licences.
- **Valkey**: The Linux Foundation fork of Redis 7.2.4, announced on 28 March 2024.
- **Redict**: A fork of Redis 7.2.4 announced on 22 March 2024, with changes under LGPL-3.0-only.
- **RDB**: Redis's snapshot file format, also used for the initial sync in replication.
- **RDB version**: The format number in the file header; a server refuses versions newer than it knows.
- **Replication**: A replica server copying a primary's data, first by snapshot, then by command stream.
- **DEBUG DIGEST**: A command that returns a hash of the whole dataset, useful for comparing two servers.
- **Floating tag**: An image tag such as latest that moves to new versions over time.
- **255.255.255**: The version that Redis development builds report instead of a release number.

## References & Further Reading

- [Redis Adopts Dual Source-Available Licensing](https://redis.io/blog/redis-adopts-dual-source-available-licensing/): Redis, 20 March 2024
- [Change license from BSD-3 to dual RSALv2+SSPLv1](https://github.com/redis/redis/pull/13157): The pull request that made the change
- [Linux Foundation Launches Open Source Valkey Community](https://www.linuxfoundation.org/press/linux-foundation-launches-open-source-valkey-community): 28 March 2024
- [Valkey repository](https://github.com/valkey-io/valkey): Source used for the tests
- [Redict is an independent, copyleft fork](https://redict.io/posts/2024-03-22-redict-is-an-independent-fork/): 22 March 2024
- [ElastiCache for Redis 7.1 generally available](https://aws.amazon.com/about-aws/whats-new/2023/11/amazon-elasticache-redis-version-7-1-generally-available): November 2023
- [The race to replace Redis](https://lwn.net/Articles/966631/): LWN, 28 March 2024
- [Sample code for this article](https://github.com/nithinmohantk/blog-samples-working-repo/tree/main/redis-valkey-licence-check): Licence classifier, workload, RDB and replication checks
