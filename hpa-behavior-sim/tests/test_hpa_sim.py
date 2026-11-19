from collections import deque
from pathlib import Path

import kubernetes_validate
import pytest
import yaml

import hpa_sim as h

MANIFEST = (Path(__file__).parent.parent / "hpa.yaml").read_text()


def test_manifest_is_valid_for_kubernetes_1_29():
    kubernetes_validate.validate(yaml.safe_load(MANIFEST), "1.29", strict=True)


def test_manifest_parses_into_spec():
    s = h.Spec.from_manifest(MANIFEST)
    assert (s.min_replicas, s.max_replicas, s.target_utilization) == (3, 40, 65)
    assert s.scale_down["stabilizationWindowSeconds"] == 600 and s.scale_down["selectPolicy"] == "Min"


def test_rejects_unsupported_metrics():
    doc = yaml.safe_load(MANIFEST)
    doc["spec"]["metrics"].append({"type": "Pods", "pods": {"metric": {"name": "rps"},
                                   "target": {"type": "AverageValue", "averageValue": "100"}}})
    with pytest.raises(ValueError):
        h.Spec.from_manifest(yaml.safe_dump(doc))


@pytest.mark.parametrize("util,expected", [(66, 4), (71, 4), (72, 5), (130, 8), (30, 2)])
def test_raw_recommendation_with_tolerance(util, expected):
    # 4 replicas, target 65: within 10% of target -> no change
    assert h.raw_recommendation(4, util, 65) == expected


def test_default_scale_up_limit_is_max_of_double_or_plus_four():
    ev = deque()
    assert h.scale_up_limit(2, h.DEFAULT_UP, ev, 0) == 6     # max(4, 6)
    assert h.scale_up_limit(10, h.DEFAULT_UP, ev, 0) == 20   # max(20, 14)


def test_scale_up_limit_counts_pods_added_in_the_period():
    rules = {"selectPolicy": "Max", "policies": [{"type": "Pods", "value": 4, "periodSeconds": 60}]}
    ev = deque([(0, 4)])                                      # 4 added at t=0, now 8
    assert h.scale_up_limit(8, rules, ev, 30) == 8           # period start was 4 -> 4 + 4
    assert h.scale_up_limit(8, rules, ev, 60) == 12          # event left the period


def test_scale_down_select_min_takes_the_smaller_change():
    rules = {"selectPolicy": "Min", "policies": [{"type": "Percent", "value": 20, "periodSeconds": 60},
                                                 {"type": "Pods", "value": 2, "periodSeconds": 60}]}
    assert h.scale_down_limit(20, rules, deque(), 0) == 18   # max(16, 18)
    assert h.scale_down_limit(5, rules, deque(), 0) == 4     # max(4, 3)


def test_disabled_policy_blocks_direction():
    assert h.scale_down_limit(10, {"selectPolicy": "Disabled", "policies": [
        {"type": "Pods", "value": 5, "periodSeconds": 15}]}, deque(), 0) == 10


def test_default_behavior_waits_300s_before_scaling_down():
    spec = h.Spec(min_replicas=2, max_replicas=20, target_utilization=50)
    load = [400.0] * 8 + [100.0] * 30                       # capacity 100/pod at 100% CPU
    rows = h.simulate(spec, load, capacity_per_pod=100, start_replicas=8)
    drop = 8
    assert all(r["replicas"] == 8 for r in rows[drop:drop + 20])    # 20 syncs = 300 s
    assert rows[drop + 21]["replicas"] < 8


def test_spike_with_manifest_behavior_and_startup_delay():
    spec = h.Spec.from_manifest(MANIFEST)
    load = [300.0] * 8 + [2400.0] * 40 + [300.0] * 80
    rows = h.simulate(spec, load, capacity_per_pod=100, startup_seconds=45)
    s = h.summarise(rows, spec.target_utilization)
    assert s["peak_replicas"] <= spec.max_replicas
    assert rows[-1]["replicas"] >= spec.min_replicas
    # Scale-up is rate limited: never more than max(2x, +4) per 15 s sync
    for a, b in zip(rows, rows[1:]):
        assert b["replicas"] <= max(2 * a["replicas"], a["replicas"] + 4)
    # Scale-down waits at least the 600 s window after the load drops
    drop = 48
    assert all(r["replicas"] == rows[drop - 1]["replicas"] for r in rows[drop:drop + 39])
