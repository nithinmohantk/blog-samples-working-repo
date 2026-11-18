"""One workload, run against each server; the results are compared value by value."""
from __future__ import annotations

import redis

LUA = "return {KEYS[1], ARGV[1], redis.call('GET', KEYS[1])}"
LIBRARY = """#!lua name=inventory
redis.register_function('reserve', function(keys, args)
  local left = tonumber(redis.call('HGET', keys[1], 'stock') or '0')
  if left < tonumber(args[1]) then return redis.error_reply('INSUFFICIENT') end
  return redis.call('HINCRBY', keys[1], 'stock', -tonumber(args[1]))
end)"""


def run(r: redis.Redis) -> dict[str, object]:
    r.flushall()
    out: dict[str, object] = {}
    out["set/get"] = (r.set("s:1", "v1"), r.get("s:1"))
    out["incrbyfloat"] = r.incrbyfloat("n:1", 2.5)
    out["hash"] = (r.hset("h:1", mapping={"a": 1, "b": 2}), sorted(r.hgetall("h:1").items()))
    out["list"] = (r.rpush("l:1", *range(5)), r.lrange("l:1", 0, -1), r.lpos("l:1", 3))
    out["set"] = (r.sadd("st:1", "x", "y", "z"), sorted(r.smembers("st:1")), r.sintercard(2, ["st:1", "st:1"]))
    out["zset"] = (r.zadd("z:1", {"a": 1, "b": 2, "c": 3}), r.zrange("z:1", 0, -1, withscores=True),
                   r.zrangestore("z:2", "z:1", 1, 2))
    out["stream"] = (r.xadd("x:1", {"k": "v"}, id="1-1"), r.xadd("x:1", {"k": "w"}, id="2-1"),
                     r.xrange("x:1"), r.xgroup_create("x:1", "g", id="0"),
                     r.xreadgroup("g", "c1", {"x:1": ">"}, count=1))
    out["hyperloglog"] = (r.pfadd("hll:1", *[f"u{i}" for i in range(100)]), r.pfcount("hll:1"))
    out["bitmap"] = (r.setbit("b:1", 7, 1), r.bitcount("b:1"), r.bitpos("b:1", 1))
    out["geo"] = (r.geoadd("g:1", (-6.2603, 53.3498, "dublin"), (-9.0568, 53.2707, "galway")),
                  round(r.geodist("g:1", "dublin", "galway", unit="km"), 3))
    out["lua"] = r.eval(LUA, 1, "s:1", "arg")
    out["function"] = (r.function_load(LIBRARY, replace=True), r.hset("inv:1", "stock", 5),
                       r.fcall("reserve", 1, "inv:1", 2))
    try:
        r.fcall("reserve", 1, "inv:1", 9)
    except redis.ResponseError as e:
        out["function error"] = str(e)
    pipe = r.pipeline(transaction=True)
    pipe.incr("t:1").incr("t:1").get("t:1")
    out["multi/exec"] = pipe.execute()
    out["encodings"] = [r.object("encoding", k) for k in ("s:1", "h:1", "l:1", "st:1", "z:1")]
    out["expire options"] = (r.expire("s:1", 1000, nx=True), r.expire("s:1", 10, gt=True))
    out["dbsize"] = r.dbsize()
    return out


def server_facts(r: redis.Redis) -> dict[str, object]:
    info = r.info("server")
    hello = r.execute_command("HELLO", 3)
    facts = {k: info.get(k) for k in ("redis_version", "redis_git_sha1", "redis_mode", "server_name",
                                      "valkey_version", "executable") if k in info}
    facts["HELLO server"] = hello.get(b"server", hello.get("server"))
    facts["HELLO version"] = hello.get(b"version", hello.get("version"))
    facts["COMMAND COUNT"] = r.execute_command("COMMAND", "COUNT")
    return facts
