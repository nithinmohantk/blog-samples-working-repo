"""How fast is the loop? A thousand sequential DynamoDB writes and reads against a local endpoint.

    python bench.py emulator:9297 out/bench-emulator.json

Sequential, one client, on whatever machine runs it. The point is the order of magnitude, not a benchmark.
"""
import json
import statistics
import sys
import time

from common import session_for

target, out_path = sys.argv[1], sys.argv[2]
session, kw = session_for(target)
ddb = session.client("dynamodb", **kw)
table = f"bench-{int(time.time())}"
ddb.create_table(TableName=table, BillingMode="PAY_PER_REQUEST",
                 AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}], KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}])
ddb.get_waiter("table_exists").wait(TableName=table, WaiterConfig={"Delay": 1, "MaxAttempts": 30})


def timed(call, count: int) -> list[float]:
    samples = []
    for i in range(count):
        started = time.perf_counter()
        call(i)
        samples.append((time.perf_counter() - started) * 1000)
    return samples


def summary(samples: list[float]) -> dict:
    ordered = sorted(samples)
    return {"calls": len(ordered), "p50_ms": round(statistics.median(ordered), 2), "p95_ms": round(ordered[int(len(ordered) * 0.95)], 2),
            "max_ms": round(ordered[-1], 2), "total_s": round(sum(ordered) / 1000, 2)}


result = {
    "target": target,
    "put_item": summary(timed(lambda i: ddb.put_item(TableName=table, Item={"id": {"S": f"k-{i}"}, "n": {"N": str(i)}}), 1000)),
    "get_item": summary(timed(lambda i: ddb.get_item(TableName=table, Key={"id": {"S": f"k-{i}"}}), 1000)),
}
print(json.dumps(result, indent=2))
with open(out_path, "w", encoding="utf-8") as handle:
    json.dump(result, handle, indent=2)
    handle.write("\n")
