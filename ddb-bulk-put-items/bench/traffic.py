"""A small application load on the target table: one PutItem and one GetItem per tick.

Used to measure what an import does to the latency of the application that owns the table.
Keys start with "app#" so they never collide with imported items.
"""
from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass, field

from botocore.exceptions import ClientError

from .common import client, percentile


@dataclass
class Window:
    label: str
    put_ms: list[float] = field(default_factory=list)
    get_ms: list[float] = field(default_factory=list)
    errors: dict[str, int] = field(default_factory=dict)

    def summary(self) -> dict:
        def s(values):
            return {"n": len(values), "p50": round(percentile(values, 50), 1),
                    "p99": round(percentile(values, 99), 1), "max": round(max(values), 1) if values else None}
        return {"label": self.label, "put_ms": s(self.put_ms), "get_ms": s(self.get_ms), "errors": self.errors}


class AppTraffic:
    def __init__(self, table: str, ops_per_second: int = 25) -> None:
        self.table = table
        self.interval = 1.0 / ops_per_second
        self.window = Window("idle")
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        # Separate client: retries disabled so throttling shows up as an error, not as hidden latency.
        import boto3
        from botocore.config import Config
        from .common import REGION
        self.ddb = boto3.client("dynamodb", config=Config(region_name=REGION, retries={"max_attempts": 1, "mode": "standard"}))

    def mark(self, label: str) -> Window:
        """Start a new measurement window and return the previous one."""
        old, self.window = self.window, Window(label)
        return old

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> Window:
        self._stop.set()
        self._thread.join()
        return self.window

    def _timed(self, fn, bucket: list[float], window: Window, **kw) -> None:
        t0 = time.perf_counter()
        try:
            fn(TableName=self.table, **kw)
            bucket.append((time.perf_counter() - t0) * 1000)
        except ClientError as err:
            code = err.response["Error"]["Code"]
            window.errors[code] = window.errors.get(code, 0) + 1

    def _run(self) -> None:
        n = 0
        while not self._stop.is_set():
            tick = time.perf_counter()
            w = self.window
            key = {"pk": {"S": f"app#{n % 5000:05d}"}}
            self._timed(self.ddb.put_item, w.put_ms, w,
                        Item={**key, "category": {"S": "app"}, "n": {"N": str(n)},
                              "pad": {"S": "x" * random.randint(200, 400)}})
            self._timed(self.ddb.get_item, w.get_ms, w, Key=key)
            n += 1
            time.sleep(max(0.0, self.interval - (time.perf_counter() - tick)))
