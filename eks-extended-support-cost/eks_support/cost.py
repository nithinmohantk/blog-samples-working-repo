"""EKS control-plane cost per cluster: $0.10 an hour in standard support, $0.60 in extended.

The extended support price applies from the April 2024 billing cycle (1 April 2024).
Before that, during the preview that began on 4 October 2023, clusters on a version
in extended support paid the standard $0.10.
"""
from __future__ import annotations

import calendar as cal
from datetime import date, timedelta
from decimal import Decimal

from .calendar import CALENDAR, support_status

STANDARD = Decimal("0.10")
EXTENDED = Decimal("0.60")
EXTENDED_PRICE_FROM = date(2024, 4, 1)


def effective_version(version: str, on: date) -> str:
    """At the end of extended support EKS upgrades the control plane to the next version.

    Follow that chain, so a cluster left alone is priced on the version it will actually run.
    """
    while support_status(version, on) == "ended":
        nxt = f"1.{int(version.split('.')[1]) + 1}"
        if nxt not in CALENDAR:
            break
        version = nxt
    return version


def hourly_rate(version: str, on: date) -> Decimal:
    version = effective_version(version, on)
    if support_status(version, on) == "extended" and on >= EXTENDED_PRICE_FROM:
        return EXTENDED
    return STANDARD


def month_cost(version: str, year: int, month: int) -> Decimal:
    """Control-plane cost for one cluster for a whole month, day by day (the rate can change mid-month)."""
    days = cal.monthrange(year, month)[1]
    total = sum((hourly_rate(version, date(year, month, d)) * 24 for d in range(1, days + 1)), Decimal(0))
    return total.quantize(Decimal("0.01"))


def months(start: date, count: int) -> list[tuple[int, int]]:
    out, y, m = [], start.year, start.month
    for _ in range(count):
        out.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def forecast(version: str, start: date, count: int = 12) -> dict[str, Decimal]:
    """Monthly cost if the cluster stays on this version, from the month of `start`."""
    return {f"{y}-{m:02d}": month_cost(version, y, m) for y, m in months(start, count)}


def first_extended_day(version: str, after: date) -> date | None:
    day = after
    for _ in range(800):
        if support_status(version, day) == "extended":
            return day
        day += timedelta(days=1)
    return None
