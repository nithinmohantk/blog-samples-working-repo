"""Replay a load trace through the HorizontalPodAutoscaler algorithm.

Implements the autoscaling/v2 decision steps the kube-controller-manager
applies on every sync (15 s by default): the replica ratio with a 0.1
tolerance, the stabilisation window, scaleUp/scaleDown rate-limit policies
with selectPolicy, and min/max replicas. Use it to see how a `behavior`
block reacts to a recorded traffic pattern before you apply it to a cluster.

Simplifications (documented so results are read correctly):
- one Resource metric with a Utilization target;
- utilisation = load / (ready replicas x capacity per pod at 100% of request);
- new pods serve traffic after `startup_seconds`; until then they are not
  counted (the real controller treats not-yet-ready pods more conservatively).
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field

import yaml

SYNC_SECONDS = 15
TOLERANCE = 0.1

DEFAULT_UP = {"stabilizationWindowSeconds": 0, "selectPolicy": "Max",
              "policies": [{"type": "Percent", "value": 100, "periodSeconds": 15},
                           {"type": "Pods", "value": 4, "periodSeconds": 15}]}
DEFAULT_DOWN = {"stabilizationWindowSeconds": 300, "selectPolicy": "Max",
                "policies": [{"type": "Percent", "value": 100, "periodSeconds": 15}]}


@dataclass
class Spec:
    min_replicas: int
    max_replicas: int
    target_utilization: int
    scale_up: dict = field(default_factory=lambda: dict(DEFAULT_UP))
    scale_down: dict = field(default_factory=lambda: dict(DEFAULT_DOWN))

    @classmethod
    def from_manifest(cls, text: str) -> "Spec":
        doc = yaml.safe_load(text)
        if doc.get("apiVersion") != "autoscaling/v2" or doc.get("kind") != "HorizontalPodAutoscaler":
            raise ValueError("expected an autoscaling/v2 HorizontalPodAutoscaler")
        spec = doc["spec"]
        metrics = spec.get("metrics", [])
        if len(metrics) != 1 or metrics[0].get("type") != "Resource" \
                or metrics[0]["resource"]["target"].get("type") != "Utilization":
            raise ValueError("the simulator supports exactly one Resource metric with a Utilization target")
        behavior = spec.get("behavior") or {}
        up = {**DEFAULT_UP, **(behavior.get("scaleUp") or {})}
        down = {**DEFAULT_DOWN, **(behavior.get("scaleDown") or {})}
        return cls(spec.get("minReplicas", 1), spec["maxReplicas"],
                   metrics[0]["resource"]["target"]["averageUtilization"], up, down)


def raw_recommendation(current: int, utilization: float, target: int) -> int:
    ratio = utilization / target
    if abs(ratio - 1.0) <= TOLERANCE:
        return current
    return math.ceil(current * ratio)


def _period_change(events: deque, now: int, period: int, direction: int) -> int:
    return sum(n for t, n in events if now - t < period and (n > 0) == (direction > 0))


def scale_up_limit(current: int, rules: dict, events: deque, now: int) -> int:
    limits = []
    for p in rules["policies"]:
        start = current - _period_change(events, now, p["periodSeconds"], +1)
        if p["type"] == "Pods":
            limits.append(start + p["value"])
        else:
            limits.append(math.ceil(start * (1 + p["value"] / 100)))
    if rules.get("selectPolicy") == "Disabled":
        return current
    return min(limits) if rules.get("selectPolicy") == "Min" else max(limits)


def scale_down_limit(current: int, rules: dict, events: deque, now: int) -> int:
    limits = []
    for p in rules["policies"]:
        start = current - _period_change(events, now, p["periodSeconds"], -1)  # removed pods are negative
        if p["type"] == "Pods":
            limits.append(start - p["value"])
        else:
            limits.append(math.floor(start * (1 - p["value"] / 100)))
    if rules.get("selectPolicy") == "Disabled":
        return current
    # Max = allow the biggest change = the lowest floor
    return max(limits) if rules.get("selectPolicy") == "Min" else min(limits)


def simulate(spec: Spec, load: list[float], capacity_per_pod: float,
             start_replicas: int | None = None, startup_seconds: int = 0) -> list[dict]:
    """Replay `load` (one value per sync period) and return one row per sync."""
    replicas = start_replicas or spec.min_replicas
    pending: deque = deque()            # (ready_at, count)
    recs: deque = deque()               # (time, recommendation)
    events: deque = deque()             # (time, +added / -removed)
    rows = []
    for i, demand in enumerate(load):
        now = i * SYNC_SECONDS
        while pending and pending[0][0] <= now:
            pending.popleft()
        not_ready = sum(c for _, c in pending)
        ready = max(1, replicas - not_ready)
        util = 100.0 * demand / (ready * capacity_per_pod)

        rec = raw_recommendation(ready, util, spec.target_utilization) + not_ready
        recs.append((now, rec))
        window = max(spec.scale_up["stabilizationWindowSeconds"], spec.scale_down["stabilizationWindowSeconds"])
        while recs and now - recs[0][0] > window:
            recs.popleft()
        up_window = [r for t, r in recs if now - t <= spec.scale_up["stabilizationWindowSeconds"]]
        down_window = [r for t, r in recs if now - t <= spec.scale_down["stabilizationWindowSeconds"]]
        up_rec, down_rec = min(up_window), max(down_window)
        desired = up_rec if replicas < up_rec else down_rec if replicas > down_rec else replicas

        if desired > replicas:
            desired = min(desired, scale_up_limit(replicas, spec.scale_up, events, now))
        elif desired < replicas:
            desired = max(desired, scale_down_limit(replicas, spec.scale_down, events, now))
        desired = max(spec.min_replicas, min(spec.max_replicas, desired))

        if desired != replicas:
            events.append((now, desired - replicas))
            if desired > replicas and startup_seconds:
                pending.append((now + startup_seconds, desired - replicas))
            if desired < replicas:
                # Remove not-ready pods first, as a ReplicaSet scale-down prefers them
                drop = replicas - desired
                while drop and pending:
                    t, c = pending.pop()
                    take = min(c, drop)
                    if c - take:
                        pending.append((t, c - take))
                    drop -= take
        rows.append({"t": now, "load": demand, "ready": ready, "utilization": round(util, 1),
                     "recommendation": rec, "replicas": desired})
        replicas = desired
        while events and now - events[0][0] > 1800:
            events.popleft()
    return rows


def summarise(rows: list[dict], target: int) -> dict:
    over = sum(1 for r in rows if r["utilization"] > 100)
    return {
        "peak_replicas": max(r["replicas"] for r in rows),
        "replica_minutes": round(sum(r["replicas"] for r in rows) * SYNC_SECONDS / 60, 1),
        "syncs_over_100pct": over,
        "syncs_over_target": sum(1 for r in rows if r["utilization"] > target),
        "changes": sum(1 for a, b in zip(rows, rows[1:]) if a["replicas"] != b["replicas"]),
    }
