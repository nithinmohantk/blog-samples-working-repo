"""Cost of public IPv4 addresses at $0.005 per address-hour (from 1 February 2024)."""
from __future__ import annotations

import calendar
from collections import Counter
from decimal import Decimal, ROUND_HALF_UP

RATE_PER_HOUR = Decimal("0.005")
FREE_TIER_HOURS = 750  # per month, first 12 months, EC2 Free Tier accounts only


def hours_in_month(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1] * 24


def month_cost(address_count: int, year: int, month: int, free_tier: bool = False) -> Decimal:
    """Cost of address_count addresses held for the whole month."""
    hours = address_count * hours_in_month(year, month)
    if free_tier:
        hours = max(0, hours - FREE_TIER_HOURS)
    return (hours * RATE_PER_HOUR).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def summarise(addresses, year: int, month: int) -> dict:
    """Totals by kind and by owner type, plus the part that is new from February 2024."""
    by_kind = Counter(a.kind for a in addresses)
    by_owner = Counter(a.owner.split(" ")[0] for a in addresses)
    newly = sum(1 for a in addresses if a.newly_charged)
    return {
        "addresses": len(addresses),
        "by_kind": dict(sorted(by_kind.items())),
        "by_owner_type": dict(sorted(by_owner.items())),
        "newly_charged": newly,
        "month": f"{year}-{month:02d}",
        "hours": hours_in_month(year, month),
        "cost_all": str(month_cost(len(addresses), year, month)),
        "cost_new_from_feb_2024": str(month_cost(newly, year, month)),
    }
