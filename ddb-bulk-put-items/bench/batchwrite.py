"""The do-it-yourself baseline: BatchWriteItem in parallel, with unprocessed items retried.

BatchWriteItem takes up to 25 puts per call. Throttled items come back in
UnprocessedItems rather than as an error, so they must be resent with backoff.
"""
from __future__ import annotations

import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from botocore.exceptions import ClientError

from .common import client
from .data import read_items

BATCH = 25
MAX_RETRIES = 12


@dataclass
class Stats:
    items: int = 0
    calls: int = 0
    write_units: float = 0.0
    unprocessed_retries: int = 0
    throttle_errors: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add(self, **kw) -> None:
        with self.lock:
            for k, v in kw.items():
                setattr(self, k, getattr(self, k) + v)


def backoff(attempt: int, base: float = 0.05, cap: float = 5.0) -> float:
    """Full jitter: a random wait up to an exponentially growing ceiling."""
    return random.uniform(0, min(cap, base * 2 ** attempt))


def write_batch(table: str, items: list[dict], stats: Stats, ddb=None) -> None:
    ddb = ddb or client("dynamodb")
    requests = [{"PutRequest": {"Item": it}} for it in items]
    attempt = 0
    while requests:
        try:
            resp = ddb.batch_write_item(RequestItems={table: requests}, ReturnConsumedCapacity="TOTAL")
        except ClientError as err:
            code = err.response["Error"]["Code"]
            if code not in ("ProvisionedThroughputExceededException", "ThrottlingException",
                            "RequestLimitExceeded") or attempt >= MAX_RETRIES:
                raise
            stats.add(throttle_errors=1)
            time.sleep(backoff(attempt))
            attempt += 1
            continue
        stats.add(calls=1, write_units=sum(c.get("CapacityUnits", 0) for c in resp.get("ConsumedCapacity", [])))
        unprocessed = resp.get("UnprocessedItems", {}).get(table, [])
        stats.add(items=len(requests) - len(unprocessed))
        if unprocessed:
            if attempt >= MAX_RETRIES:
                raise RuntimeError(f"{len(unprocessed)} items still unprocessed after {MAX_RETRIES} retries")
            stats.add(unprocessed_retries=1)
            time.sleep(backoff(attempt))
            attempt += 1
        requests = unprocessed


def chunks(items: Iterable[dict], size: int = BATCH):
    batch: list[dict] = []
    for it in items:
        batch.append(it)
        if len(batch) == size:
            yield batch
            batch = []
    if batch:
        yield batch


def load(table: str, files: list[Path], workers: int = 16) -> Stats:
    stats = Stats()

    def one_file(path: Path) -> None:
        for batch in chunks(read_items(path)):
            write_batch(table, batch, stats)

    # One thread per file at a time; files are similar in size, so the load stays even.
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for future in [pool.submit(one_file, f) for f in files]:
            future.result()
    return stats
