"""Compare the default behavior with hpa.yaml on two traces (one value per 15 s sync)."""
from pathlib import Path

import hpa_sim as h

traces = {
    "2-min dip, 45 s startup": ([300.0] * 20 + [2400.0] * 20 + [500.0] * 8 + [2400.0] * 20 + [300.0] * 80, 45),
    "7-min dip, 120 s startup": ([300.0] * 20 + [2400.0] * 20 + [500.0] * 28 + [2400.0] * 20 + [300.0] * 80, 120),
}
tuned = h.Spec.from_manifest(Path("hpa.yaml").read_text())
default = h.Spec(tuned.min_replicas, tuned.max_replicas, tuned.target_utilization)

for trace, (load, startup) in traces.items():
    print(trace)
    for name, spec in [("default behavior", default), ("hpa.yaml behavior", tuned)]:
        s = h.summarise(h.simulate(spec, load, capacity_per_pod=100, startup_seconds=startup), spec.target_utilization)
        print(f"  {name:<18} replica-minutes={s['replica_minutes']:>7} saturated syncs={s['syncs_over_100pct']:>2} "
              f"over target={s['syncs_over_target']:>2} changes={s['changes']}")
