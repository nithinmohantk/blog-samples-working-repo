import promql_parser
import pytest
import yaml

import slo_rules as s

SLO = s.SLO("orders-api", 0.999,
            total='http_requests_total{job="orders-api"}',
            errors='http_requests_total{job="orders-api",code=~"5.."}')


@pytest.mark.parametrize("share,window,expected", [(0.02, "1h", 14.4), (0.05, "6h", 6.0), (0.10, "3d", 1.0)])
def test_workbook_burn_rates_for_30_days(share, window, expected):
    assert s.burn_rate_threshold(share, window) == expected


def test_burn_rates_scale_with_period():
    assert s.burn_rate_threshold(0.02, "1h", "28d") == 13.44


@pytest.mark.parametrize("objective,minutes", [(0.999, 43.2), (0.9995, 21.6), (0.99, 432.0)])
def test_error_budget_minutes(objective, minutes):
    assert s.error_budget_minutes(objective) == minutes


def test_every_expression_parses_as_promql():
    doc = s.rule_file(SLO)
    exprs = [r["expr"] for g in doc["groups"] for r in g["rules"]]
    assert len(exprs) == 5 + 3                      # five windows recorded, three alerts
    for e in exprs:
        promql_parser.parse(e)                       # raises on invalid PromQL


def test_alerts_use_long_and_short_windows_and_budget():
    alerts = s.alert_rules(SLO)
    first = alerts[0]
    assert first["alert"] == "SLOErrorBudgetBurn1h"
    assert 'slo:error_ratio:rate1h{service="orders-api"} > (14.4 * 0.001)' in first["expr"]
    assert 'slo:error_ratio:rate5m{service="orders-api"} > (14.4 * 0.001)' in first["expr"]
    assert [a["labels"]["severity"] for a in alerts] == ["page", "page", "ticket"]


def test_recording_rules_cover_all_windows_in_order():
    recs = s.recording_rules(SLO)
    assert [r["record"] for r in recs] == [f"slo:error_ratio:rate{w}" for w in ["5m", "30m", "1h", "6h", "3d"]]


def test_cli_writes_loadable_yaml(capsys):
    assert s.main(["--service", "orders-api", "--objective", "0.999",
                   "--total", "x_total", "--errors", 'x_total{code="500"}']) == 0
    out = capsys.readouterr()
    doc = yaml.safe_load(out.out)
    assert {g["name"] for g in doc["groups"]} == {"slo-orders-api-recording", "slo-orders-api-alerts"}
    assert "43.2 minutes" in out.err


@pytest.mark.parametrize("kwargs", [{"service": "Orders API"}, {"objective": 1.0}, {"objective": 99.9}])
def test_invalid_slo_rejected(kwargs):
    base = dict(service="orders-api", objective=0.999, total="a", errors="b")
    base.update(kwargs)
    with pytest.raises(ValueError):
        s.SLO(**base)


def test_bad_window_rejected():
    with pytest.raises(ValueError):
        s.seconds("1w")
