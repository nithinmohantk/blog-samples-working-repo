"""Pure functions over kubectl output and the event logs. No cluster needed."""
from __future__ import annotations

import json
from datetime import datetime


def parse_stream(text: str) -> list[dict]:
    """Split the concatenated JSON objects that `kubectl get -o json --watch` prints.

    Stopping the watch can cut the last object short, so a truncated tail is dropped.
    """
    decoder, objects, i = json.JSONDecoder(), [], 0
    while i < len(text):
        while i < len(text) and text[i].isspace():
            i += 1
        if i >= len(text):
            break
        try:
            obj, i = decoder.raw_decode(text, i)
        except json.JSONDecodeError:
            break  # the watch was stopped mid-object; keep what was complete
        objects.append(obj)
    return objects


def _ts(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def containers(pod: dict) -> dict[str, dict]:
    """Per container: kind, started, finished, exit code, reason, restarts, ready."""
    out = {}
    status = pod.get("status", {})
    for kind, key in (("init", "initContainerStatuses"), ("main", "containerStatuses")):
        for c in status.get(key, []) or []:
            state = c.get("state", {})
            running, terminated = state.get("running"), state.get("terminated")
            out[c["name"]] = {
                "kind": kind,
                "started": (running or terminated or {}).get("startedAt"),
                "finished": (terminated or {}).get("finishedAt"),
                "exit_code": (terminated or {}).get("exitCode"),
                "reason": (terminated or state.get("waiting") or {}).get("reason"),
                "restarts": c.get("restartCount", 0),
                "ready": c.get("ready", False),
            }
    return out


def seconds_between(a: str | None, b: str | None) -> float | None:
    if not a or not b:
        return None
    return (_ts(b) - _ts(a)).total_seconds()


def last_terminated(snapshots: list[dict]) -> dict[str, dict]:
    """The last terminated state seen for each container across a watch stream."""
    seen: dict[str, dict] = {}
    for pod in snapshots:
        for name, c in containers(pod).items():
            if c["finished"]:
                seen[name] = c
    return seen


def parse_events(text: str) -> list[tuple[float, str, str]]:
    """Lines of '<uptime seconds> <container> <event>' from the host event log, in time order."""
    rows = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 3:
            rows.append((float(parts[0]), parts[1], parts[2]))
    return sorted(rows)


def relative(events: list[tuple[float, str, str]], origin: tuple[str, str]) -> list[tuple[float, str, str]]:
    """Shift times so that the first (container, event) matching origin is 0."""
    zero = next(t for t, c, e in events if (c, e) == origin)
    return [(round(t - zero, 2), c, e) for t, c, e in events if t >= zero]
