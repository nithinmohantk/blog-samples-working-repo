"""Redis 7.2.4 and Valkey side by side: facts, workload, RDB files both ways, replication both ways.

    python tools/run_checks.py <redis-server binary> <valkey server binary> <work dir> <output dir>
"""
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import redis

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rvcheck.licence import classify  # noqa: E402
from rvcheck.workload import run, server_facts  # noqa: E402

REDIS_BIN, VALKEY_BIN, WORK, OUT = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4])
OUT.mkdir(parents=True, exist_ok=True)
log = []


def say(line=""):
    print(line, flush=True)
    log.append(line)


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


def alive(r: redis.Redis) -> bool:
    try:
        return bool(r.ping())
    except redis.RedisError:
        return False


def log_lines(name: str, *needles: str) -> list[str]:
    text = (WORK / name / "server.log").read_text(errors="replace").splitlines()
    return [line.split(" * ", 1)[-1].split(" # ", 1)[-1] for line in text if any(n in line for n in needles)]


def rdb_header(r: redis.Redis, name: str) -> str:
    r.save()
    return (WORK / name / "dump.rdb").read_bytes()[:9].decode()


def wait_link(r: redis.Redis, seconds: float = 15) -> str:
    deadline = time.time() + seconds
    status = "unknown"
    while time.time() < deadline:
        status = r.info("replication").get("master_link_status", "none")
        if status == "up":
            break
        time.sleep(0.25)
    return status


src_redis = start(REDIS_BIN, 7001, "redis-724")
src_valkey = start(VALKEY_BIN, 7002, "valkey")

say("== 1. What each server says about itself")
facts = {}
for label, r in (("Redis 7.2.4", src_redis), ("Valkey unstable", src_valkey)):
    f = server_facts(r)
    f.pop("executable", None)
    facts[label] = f
    lic = classify(r.info("server"))
    say(f"{label}: " + ", ".join(f"{k}={v}" for k, v in f.items()))
    say(f"  licence check: {lic.product} {lic.version}: {lic.licence}{(' (' + lic.note + ')') if lic.note else ''}")

say("\n== 2. The same workload on both (redis-py)")
a, b = run(src_redis), run(src_valkey)
diff = [k for k in a if a[k] != b.get(k)]
say(f"{len(a)} checks, {len(a) - len(diff)} identical" + (f"; different: {', '.join(diff)}" if diff else ""))
for k in diff:
    say(f"  {k}: redis={a[k]!r} valkey={b[k]!r}")
say(f"digest after workload: redis {src_redis.execute_command('DEBUG', 'DIGEST')} "
    f"valkey {src_valkey.execute_command('DEBUG', 'DIGEST')}")

say("\n== 3. RDB files")
h_redis, h_valkey = rdb_header(src_redis, "redis-724"), rdb_header(src_valkey, "valkey")
say(f"RDB header written by Redis 7.2.4: {h_redis}; by Valkey unstable: {h_valkey}")
v_from_r = start(VALKEY_BIN, 7003, "valkey-from-redis-rdb", WORK / "redis-724" / "dump.rdb")
say(f"Redis 7.2.4 RDB -> Valkey: started={alive(v_from_r)}"
    + (f", keys={v_from_r.dbsize()}, same digest={v_from_r.execute_command('DEBUG', 'DIGEST') == src_redis.execute_command('DEBUG', 'DIGEST')}"
       f", functions={[f['library_name'] for f in v_from_r.function_list()]}" if alive(v_from_r) else ""))
r_from_v = start(REDIS_BIN, 7004, "redis-from-valkey-rdb", WORK / "valkey" / "dump.rdb")
time.sleep(1)
say(f"Valkey RDB -> Redis 7.2.4: started={alive(r_from_v)}")
for line in log_lines("redis-from-valkey-rdb", "RDB", "rdb", "version"):
    say(f"  log: {line}")

say("\n== 4. Replication")
v_replica = start(VALKEY_BIN, 7005, "valkey-replica-of-redis")
v_replica.replicaof("127.0.0.1", 7001)
say(f"Valkey replica of Redis 7.2.4: link {wait_link(v_replica)}")
src_redis.set("after-sync", "written on the Redis primary")
time.sleep(1)
say(f"  key written after sync, read on the Valkey replica: {v_replica.get('after-sync')!r}; "
    f"digests equal: {v_replica.execute_command('DEBUG', 'DIGEST') == src_redis.execute_command('DEBUG', 'DIGEST')}")
r_replica = start(REDIS_BIN, 7006, "redis-replica-of-valkey")
r_replica.replicaof("127.0.0.1", 7002)
say(f"Redis 7.2.4 replica of Valkey: link {wait_link(r_replica)} after 15 s")
for line in sorted(set(log_lines("redis-replica-of-valkey", "RDB", "rdb", "MASTER <-> REPLICA sync", "Can't"))):
    say(f"  log: {line}")

for port in (7001, 7002, 7003, 7004, 7005, 7006):
    try:
        redis.Redis(port=port).shutdown(nosave=True)
    except redis.RedisError:
        pass

(OUT / "checks.txt").write_text("\n".join(log) + "\n")
(OUT / "results.json").write_text(json.dumps({"facts": facts, "workload_diff": diff,
                                              "rdb_headers": [h_redis, h_valkey]}, indent=2, default=str))
