# hpa-behavior-sim

Companion code for the dataa.dev article *Horizontal Pod Autoscaling: How the Algorithm Decides, and How to Tune It* (14 March 2024).

`hpa_sim.py` replays a load trace through the HorizontalPodAutoscaler (autoscaling/v2) decision steps: the replica ratio with the 0.1 tolerance, stabilisation windows, `scaleUp`/`scaleDown` rate-limit policies with `selectPolicy`, and min/max replicas. Use it to see what a `behavior` block will do with your traffic before you apply it.

`hpa.yaml` is the example HPA from the article. It validates against the Kubernetes 1.29 schema.

## Use

```bash
pip install pyyaml==6.0.1
python example.py
```

```
2-min dip, 45 s startup
  default behavior   replica-minutes=  792.0 saturated syncs= 4 over target= 8 changes=6
  hpa.yaml behavior  replica-minutes= 1207.0 saturated syncs= 4 over target= 8 changes=15
7-min dip, 120 s startup
  default behavior   replica-minutes=  963.2 saturated syncs=17 over target=26 changes=14
  hpa.yaml behavior  replica-minutes= 1450.2 saturated syncs= 8 over target=16 changes=19
```

On the first trace the slower scale-down costs about 50% more replica-minutes and buys nothing. On the second, where the dip outlasts the default 5-minute window and pods take 2 minutes to start, it halves the time spent saturated. That is the trade-off to check with your own traces.

Build a trace from your metrics: one demand value per 15 seconds, in the same unit as `capacity_per_pod` (for example requests per second a pod handles at 100% of its CPU request).

## Simplifications

- One `Resource` metric with a `Utilization` target.
- New pods serve traffic after `startup_seconds`; the real controller treats not-yet-ready pods more conservatively.
- No metric lag or noise. Results show the shape of the behaviour, not exact replica counts.

## Tests

```bash
pip install pyyaml==6.0.1 kubernetes-validate==1.29.1 pytest==8.0.2
python -m pytest -q
```

14 tests: schema validation of `hpa.yaml` for Kubernetes 1.29, tolerance, default and custom rate limits, `selectPolicy` Min/Max/Disabled, the default 300-second scale-down window, and a spike with startup delay. Tested with Python 3.13.
