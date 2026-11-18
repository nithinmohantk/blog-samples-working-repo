"""Turn results.json into a plain-text table."""
from __future__ import annotations

import json
import sys
from pathlib import Path


def mb(value):
    return "-" if value is None else f"{value / 1024 / 1024:.0f}"


def table(results: dict) -> str:
    head = ("container", "experiment", "mem", "workers", "seen", "build s", "WAL MB", "index MB",
            "recall ef40", "recall ef100", "outcome")
    lines = [head]
    for r in results["runs"]:
        if r["error"]:
            outcome = r["error"]
        elif any("no longer fits" in n for n in r["notices"]):
            outcome = "graph spilled to disk"
        else:
            outcome = "in memory"
        lines.append((r["label"], r["experiment"], r["maintenance_work_mem"], str(r["workers_requested"]),
                      str(r["max_parallel_workers_seen"]), "-" if r["seconds"] is None else f"{r['seconds']:.1f}",
                      mb(r["wal_bytes"]), mb(r["index_bytes"]),
                      f"{r['recall'].get('40', 0):.3f}" if r["recall"] else "-",
                      f"{r['recall'].get('100', 0):.3f}" if r["recall"] else "-", outcome))
    widths = [max(len(row[i]) for row in lines) for i in range(len(head))]
    return "\n".join("  ".join(cell.ljust(w) for cell, w in zip(row, widths)).rstrip() for row in lines)


if __name__ == "__main__":
    print(table(json.loads(Path(sys.argv[1]).read_text())))
