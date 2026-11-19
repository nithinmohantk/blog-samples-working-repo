import pytest

from costmodel import Candidate, compare, cost_per_million, instances_needed, monthly_cost


def test_cost_per_million_at_full_and_partial_utilisation():
    c = Candidate("x", hourly_usd=36.0, replicas_per_instance=1, tokens_per_second=1000)
    # 3.6M tokens per hour for $36 -> $10 per million
    assert cost_per_million(c) == pytest.approx(10.0)
    # Half busy doubles the effective price
    assert cost_per_million(c, 0.5) == pytest.approx(20.0)


def test_replicas_multiply_capacity():
    one = Candidate("a", 10.0, 1, 500)
    two = Candidate("b", 10.0, 2, 500)
    assert cost_per_million(two) == pytest.approx(cost_per_million(one) / 2)


def test_instances_needed_with_headroom():
    c = Candidate("x", 10.0, 2, 500)       # 1000 tok/s per instance, 800 usable at 20% headroom
    assert instances_needed(c, 800) == 1
    assert instances_needed(c, 801) == 2
    assert instances_needed(c, 2400, headroom=0.0) == 3


def test_monthly_cost():
    assert monthly_cost(Candidate("x", 2.0, 1, 1), 3) == pytest.approx(4380.0)


def test_compare_ranks_by_monthly_cost_and_reports_utilisation():
    cheap_slow = Candidate("slow", 13.0, 1, 400)
    dear_fast = Candidate("fast", 55.0, 1, 3000)
    rows = compare([dear_fast, cheap_slow], peak_tokens_per_second=1000,
                   monthly_tokens=1_000 * 3600 * 730 * 0.3)
    assert [r["name"] for r in rows] == ["slow", "fast"]
    slow = rows[0]
    assert slow["instances"] == 4          # 400 * 0.8 = 320 usable -> ceil(1000/320)
    assert 0 < slow["utilisation"] < 1
    assert slow["usd_per_million"] == pytest.approx(slow["monthly_usd"] / (1000 * 3600 * 730 * 0.3) * 1e6, rel=1e-3)


@pytest.mark.parametrize("kwargs", [
    {"hourly_usd": 0, "replicas_per_instance": 1, "tokens_per_second": 1},
    {"hourly_usd": 1, "replicas_per_instance": 0, "tokens_per_second": 1},
    {"hourly_usd": 1, "replicas_per_instance": 1, "tokens_per_second": 0},
])
def test_rejects_bad_inputs(kwargs):
    with pytest.raises(ValueError):
        Candidate("bad", **kwargs)


def test_rejects_bad_utilisation():
    c = Candidate("x", 1, 1, 1)
    with pytest.raises(ValueError):
        cost_per_million(c, 0)
    with pytest.raises(ValueError):
        cost_per_million(c, 1.5)
