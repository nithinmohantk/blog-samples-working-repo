# slo-burn-rate-rules

Companion code for the dataa.dev article *SRE on Azure Kubernetes Service: SLOs, Error Budgets and the Tools That Support Them* (28 November 2024).

`slo_rules.py` turns an availability objective and two Prometheus counters (all requests, failed requests) into:

- recording rules for the error ratio over 5m, 30m, 1h, 6h and 3d;
- the three multiwindow, multi-burn-rate alerts from the Google SRE Workbook: page at 14.4x over 1h and 5m, page at 6x over 6h and 30m, ticket at 1x over 3d and 6h (for a 30-day period; thresholds scale with `--period`);
- the error budget in minutes, printed to stderr.

`example.rules.yaml` is the output for a 99.9% objective.

## Use

```bash
pip install pyyaml==6.0.2
python slo_rules.py --service orders-api --objective 0.999 \
  --total 'http_requests_total{job="orders-api"}' \
  --errors 'http_requests_total{job="orders-api",code=~"5.."}' > orders-slo.rules.yaml
```

The file loads into self-managed Prometheus. Azure Monitor managed service for Prometheus evaluates the same PromQL in rule groups defined as Azure resources (ARM, Bicep or Terraform); copy the `record`/`alert` entries into those definitions.

## Tests

```bash
pip install pyyaml==6.0.2 promql-parser==0.4.1 pytest==8.3.3
python -m pytest -q
```

15 tests: the workbook burn rates (14.4, 6, 1) and their scaling for a 28-day period, error budget minutes, every generated expression parsed by a PromQL parser, window coverage, CLI output and input validation. Tested with Python 3.12.
