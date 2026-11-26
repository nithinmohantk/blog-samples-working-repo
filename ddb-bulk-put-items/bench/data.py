"""Synthetic order items, about 1 KB each, as gzip JSON Lines in DynamoDB JSON.

The same files feed BatchWriteItem, bulk put items and ImportTable: all three accept
one {"Item": {...}} object per line. Bulk put items also accepts per-record conditions.
"""
from __future__ import annotations

import gzip
import json
import random
from pathlib import Path
from typing import Iterator

CATEGORIES = [f"cat-{i:02d}" for i in range(20)]
WORDS = ("shipment parcel carrier depot route invoice customer pallet scan delivered "
         "delayed customs warehouse returned label tracking postcode signature").split()
TARGET_BYTES = 1000


def _notes(count: int = 512, seed: int = 11) -> list[str]:
    rng = random.Random(seed)
    notes = []
    for _ in range(count):
        words: list[str] = []
        while sum(len(w) + 1 for w in words) < 800:
            words.append(rng.choice(WORDS))
        notes.append(" ".join(words))
    return notes


NOTES = _notes()  # building a note per item is the slow part, so pick from a fixed pool


def item(n: int, rng: random.Random) -> dict:
    """One item in DynamoDB JSON. Deterministic for a given n and seed."""
    return {
        "pk": {"S": f"order#{n:09d}"},
        "category": {"S": CATEGORIES[n % len(CATEGORIES)]},
        "version": {"N": "1"},
        "amount": {"N": f"{rng.randint(100, 99999) / 100:.2f}"},
        "status": {"S": rng.choice(["NEW", "PACKED", "SHIPPED", "DELIVERED"])},
        "note": {"S": rng.choice(NOTES)},
    }


def records(start: int, count: int, seed: int = 7, condition: str | None = None) -> Iterator[dict]:
    rng = random.Random(seed + start)
    for n in range(start, start + count):
        rec: dict = {"Item": item(n, rng)}
        if condition:
            rec["ConditionExpression"] = condition
        yield rec


def write_files(out: Path, total: int, files: int, condition: str | None = None, seed: int = 7) -> list[Path]:
    """Split `total` records evenly across `files` gzip objects (AWS: similar sizes help parallelism)."""
    out.mkdir(parents=True, exist_ok=True)
    per_file = -(-total // files)
    paths = []
    for f in range(files):
        start = f * per_file
        count = min(per_file, total - start)
        if count <= 0:
            break
        path = out / f"part-{f:03d}.json.gz"
        with gzip.open(path, "wt", encoding="utf-8", compresslevel=6) as fh:
            for rec in records(start, count, seed, condition):
                fh.write(json.dumps(rec, separators=(",", ":")) + "\n")
        paths.append(path)
    return paths


def read_items(path: Path) -> Iterator[dict]:
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)["Item"]


def error_files(out: Path) -> list[Path]:
    """Two small objects for the error-handling run.

    good-with-bad-records: 1,000 records, three of them invalid as whole records
      (no partition key, partition key of the wrong type, item over 400 KB).
    truncated: 500 good records, then a line of broken JSON, then 500 more.
    """
    out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(99)
    bad_rows = {100: "missing-key", 400: "wrong-key-type", 700: "too-large"}
    a = out / "good-with-bad-records.json.gz"
    with gzip.open(a, "wt", encoding="utf-8") as fh:
        for n in range(1000):
            it = item(10_000_000 + n, rng)
            kind = bad_rows.get(n)
            if kind == "missing-key":
                del it["pk"]
            elif kind == "wrong-key-type":
                it["pk"] = {"N": str(n)}
            elif kind == "too-large":
                it["note"] = {"S": "x" * 410_000}
            fh.write(json.dumps({"Item": it}, separators=(",", ":")) + "\n")
    b = out / "truncated.json.gz"
    with gzip.open(b, "wt", encoding="utf-8") as fh:
        for n in range(1000):
            if n == 500:
                fh.write('{"Item":{"pk":{"S":"broken"},"note":{"S":"no closing braces"\n')
            fh.write(json.dumps({"Item": item(20_000_000 + n, rng)}, separators=(",", ":")) + "\n")
    return [a, b]
