"""Asks every service boto3 knows about one harmless question and records the kind of answer.

    python coverage.py emulator:9297 out/coverage.json

For each service it picks the first List*/Describe*/Get* operation that needs no parameters and calls it.
A 2xx means the service answers; HTTP 501 is the emulator saying the operation is not built yet. One
operation is a thin sample of a service, so this measures reach, not depth.
"""
import collections
import json
import sys
import time

import botocore.exceptions

from common import session_for

target, out_path = sys.argv[1], sys.argv[2]
session, kw = session_for(target)
kw["config"] = kw["config"].merge(__import__("botocore.config", fromlist=["Config"]).Config(read_timeout=8, connect_timeout=3))
rows, tally = [], collections.Counter()
for service in session.get_available_services():
    try:
        client = session.client(service, **kw)
    except Exception as error:  # noqa: BLE001
        rows.append({"service": service, "result": "client could not be created", "detail": type(error).__name__})
        tally["client could not be created"] += 1
        continue
    model = client.meta.service_model
    chosen = None
    for name in sorted(model.operation_names):
        if not name.startswith(("List", "Describe", "Get")):
            continue
        shape = model.operation_model(name).input_shape
        if shape is None or not shape.required_members:
            chosen = name
            break
    if chosen is None:
        rows.append({"service": service, "result": "no parameterless read operation"})
        tally["no parameterless read operation"] += 1
        continue
    method = next(py for py, api in client.meta.method_to_api_mapping.items() if api == chosen)
    started = time.perf_counter()
    try:
        getattr(client, method)()
        result = "answers"
    except botocore.exceptions.ClientError as error:
        status = error.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        result = "not implemented (501)" if status == 501 else f"error {status}"
    except Exception as error:  # noqa: BLE001
        result = f"transport: {type(error).__name__}"
    rows.append({"service": service, "operation": chosen, "result": result, "ms": round((time.perf_counter() - started) * 1000, 1)})
    tally[result.split(":")[0] if result.startswith("transport") else result] += 1

print(f"{len(rows)} services in boto3 {__import__('boto3').__version__}")
for result, count in tally.most_common():
    print(f"  {count:4}  {result}")
with open(out_path, "w", encoding="utf-8") as handle:
    json.dump({"target": target, "boto3": __import__("boto3").__version__, "tally": dict(tally), "rows": rows}, handle, indent=1)
    handle.write("\n")
