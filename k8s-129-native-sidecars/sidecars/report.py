"""Print a short summary of results.json, one block per scenario."""
from __future__ import annotations

import json
import sys
from pathlib import Path


def summary(results: dict) -> str:
    lines = []
    for key, r in results.items():
        lines.append(f"[{key}] server {r.get('server')}")
        if "error" in r:
            lines.append(f"  error: {r['error']}")
        for field in ("job_condition", "seconds_to_condition", "pod_phase", "main_started_after_proxy_s",
                      "delete_returned_after_s", "stored_restartPolicy", "job_condition_after_45s"):
            if field in r:
                lines.append(f"  {field}: {r[field]}")
        for name, c in (r.get("containers") or {}).items():
            lines.append(f"  {name:<15} {c['kind']:<4} reason={c['reason']} exit={c['exit_code']} restarts={c['restarts']}")
        for t, name, event in r.get("events", []):
            lines.append(f"  {t:>6.2f}s  {name:<15} {event}")
        for name, s in (r.get("final_states") or {}).items():
            lines.append(f"  final {name:<15} exit={s['exit_code']} reason={s['reason']}")
    return "\n".join(lines)


if __name__ == "__main__":
    print(summary(json.loads(Path(sys.argv[1]).read_text())))
