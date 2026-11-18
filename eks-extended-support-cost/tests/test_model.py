from datetime import date
from decimal import Decimal

import pytest

from eks_support.calendar import support_status
from eks_support.cost import effective_version, first_extended_day, forecast, month_cost
from eks_support.upgrade_path import steps


@pytest.mark.parametrize("version,day,expected", [
    ("1.23", date(2023, 10, 10), "standard"), ("1.23", date(2023, 10, 11), "extended"),
    ("1.24", date(2024, 1, 30), "standard"), ("1.24", date(2024, 1, 31), "extended"),
    ("1.24", date(2025, 1, 31), "ended"), ("1.29", date(2024, 2, 24), "standard"), ("1.30", date(2024, 2, 24), "unknown"),
])
def test_support_status(version, day, expected):
    assert support_status(version, day) == expected


def test_extended_support_is_billed_at_the_standard_rate_until_april_2024():
    assert month_cost("1.24", 2024, 3) == Decimal("74.40")   # 744 h x $0.10
    assert month_cost("1.24", 2024, 4) == Decimal("432.00")  # 720 h x $0.60


def test_a_month_that_crosses_end_of_standard_support_is_split():
    # 1.25: standard until 1 May 2024 (month only), so all of May is extended
    assert month_cost("1.25", 2024, 4) == Decimal("72.00")
    assert month_cost("1.25", 2024, 5) == Decimal("446.40")


def test_end_of_extended_support_means_an_automatic_upgrade_to_the_next_version():
    assert effective_version("1.23", date(2024, 10, 11)) == "1.24"
    # 1.23 in October 2024: 10 days on 1.23 extended, then 1.24, also extended
    assert month_cost("1.23", 2024, 10) == Decimal("446.40")


def test_forecast_and_first_extended_day():
    f = forecast("1.29", date(2024, 2, 24))
    assert list(f)[0] == "2024-02" and set(f.values()) <= {Decimal("69.60"), Decimal("72.00"), Decimal("74.40"), Decimal("67.20")}
    assert first_extended_day("1.27", date(2024, 2, 24)) == date(2024, 7, 1)
    assert first_extended_day("1.24", date(2024, 2, 24)) == date(2024, 2, 24)


def test_upgrade_steps_one_minor_at_a_time():
    path = steps("1.24", "1.29")
    assert [s["to"] for s in path] == ["1.25", "1.26", "1.27", "1.28", "1.29"]
    assert any("PodSecurityPolicy" in r for r in path[0]["removed"])
    assert path[3]["removed"] == []
    with pytest.raises(ValueError):
        steps("1.29", "1.28")
