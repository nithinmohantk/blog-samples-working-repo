"""Generate Prometheus recording and alerting rules for an availability SLO.

Implements the multiwindow, multi-burn-rate alerts from the Google SRE
Workbook ("Alerting on SLOs"): each alert fires only when the error budget is
burning faster than a threshold over both a long and a short window, so it
catches real incidents quickly and clears soon after they end.

The output is a standard Prometheus rule file for self-managed Prometheus.
Azure Monitor managed service for Prometheus evaluates the same PromQL
expressions in its rule groups, which are defined as Azure resources (ARM,
Bicep or Terraform), so the expressions can be copied across.

Usage:
    python slo_rules.py --service orders-api --objective 0.999 \
        --total 'http_requests_total{job="orders-api"}' \
        --errors 'http_requests_total{job="orders-api",code=~"5.."}' > orders-slo.rules.yaml
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass

import yaml

# (severity, long window, short window, share of the budget consumed when the alert fires)
WORKBOOK_TIERS = [
    ("page", "1h", "5m", 0.02),
    ("page", "6h", "30m", 0.05),
    ("ticket", "3d", "6h", 0.10),
]

_UNITS = {"m": 60, "h": 3600, "d": 86400}


def seconds(window: str) -> int:
    m = re.fullmatch(r"(\d+)([mhd])", window)
    if not m:
        raise ValueError(f"bad window {window!r}; use e.g. 5m, 1h, 3d")
    return int(m.group(1)) * _UNITS[m.group(2)]


def burn_rate_threshold(budget_share: float, long_window: str, slo_period: str = "30d") -> float:
    """Burn rate at which `budget_share` of the period's budget is spent in `long_window`."""
    return round(budget_share * seconds(slo_period) / seconds(long_window), 3)


def error_budget_minutes(objective: float, slo_period: str = "30d") -> float:
    """Minutes of total unavailability the objective allows over the period."""
    if not 0 < objective < 1:
        raise ValueError("objective must be between 0 and 1, e.g. 0.999")
    return round((1 - objective) * seconds(slo_period) / 60, 2)


@dataclass
class SLO:
    service: str
    objective: float
    total: str         # selector for all requests, a counter
    errors: str        # selector for failed requests, a counter
    period: str = "30d"

    def __post_init__(self):
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", self.service):
            raise ValueError("service must be lower-case letters, digits and hyphens")
        error_budget_minutes(self.objective, self.period)


def windows(slo: SLO) -> list[str]:
    ws = {w for _, lw, sw, _ in WORKBOOK_TIERS for w in (lw, sw)}
    return sorted(ws, key=seconds)


def recording_rules(slo: SLO) -> list[dict]:
    rules = []
    for w in windows(slo):
        rules.append({
            "record": f"slo:error_ratio:rate{w}",
            "expr": f"sum(rate({slo.errors}[{w}])) / sum(rate({slo.total}[{w}]))",
            "labels": {"service": slo.service},
        })
    return rules


def alert_rules(slo: SLO) -> list[dict]:
    budget = round(1 - slo.objective, 6)
    sel = f'{{service="{slo.service}"}}'
    rules = []
    for severity, lw, sw, share in WORKBOOK_TIERS:
        rate = burn_rate_threshold(share, lw, slo.period)
        rules.append({
            "alert": f"SLOErrorBudgetBurn{lw}",
            "expr": (f"slo:error_ratio:rate{lw}{sel} > ({rate} * {budget})\n"
                     f"and\nslo:error_ratio:rate{sw}{sel} > ({rate} * {budget})"),
            "for": "2m" if severity == "page" else "15m",
            "labels": {"severity": severity, "service": slo.service},
            "annotations": {
                "summary": f"{slo.service} is spending its error budget {rate}x too fast",
                "description": (f"Over {lw} (confirmed over {sw}) {slo.service} is failing fast enough to "
                                f"spend {share:.0%} of its {slo.period} error budget. Objective {slo.objective:.3%}."),
            },
        })
    return rules


class _Dumper(yaml.SafeDumper):
    pass


def _str(dumper, value):
    style = "|" if "\n" in value else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style=style)


_Dumper.add_representer(str, _str)


def rule_file(slo: SLO) -> dict:
    return {"groups": [
        {"name": f"slo-{slo.service}-recording", "interval": "1m", "rules": recording_rules(slo)},
        {"name": f"slo-{slo.service}-alerts", "rules": alert_rules(slo)},
    ]}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--service", required=True)
    ap.add_argument("--objective", type=float, required=True)
    ap.add_argument("--total", required=True)
    ap.add_argument("--errors", required=True)
    ap.add_argument("--period", default="30d")
    a = ap.parse_args(argv)
    slo = SLO(a.service, a.objective, a.total, a.errors, a.period)
    print(f"# Error budget: {error_budget_minutes(slo.objective, slo.period)} minutes per {slo.period}",
          file=sys.stderr)
    yaml.dump(rule_file(slo), sys.stdout, Dumper=_Dumper, sort_keys=False, width=200)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
