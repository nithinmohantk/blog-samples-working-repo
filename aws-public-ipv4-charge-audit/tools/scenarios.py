"""Price the clean-up of the demo estate, one step at a time, for March 2024 (744 hours).

Each step names the change and how many public IPv4 addresses it removes or adds.
The counts are the demo account's; replace them with your own audit's numbers.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ipv4_audit.cost import hours_in_month, month_cost  # noqa: E402

START = 10  # addresses found by tools/demo_account.py
STEPS = [
    ("Release the 2 idle Elastic IPs", -2),
    ("Stop or terminate the forgotten us-east-1 instance", -1),
    ("Replace the bastion's Elastic IP with an EC2 Instance Connect Endpoint", -1),
    ("Move the 4 web instances to private subnets behind an internet-facing ALB in 2 AZs", -4 + 2),
]


def main(year: int = 2024, month: int = 3) -> list[tuple[str, int, str]]:
    rows = [("As found", START, str(month_cost(START, year, month)))]
    count = START
    for name, delta in STEPS:
        count += delta
        rows.append((name, count, str(month_cost(count, year, month))))
    print(f"{year}-{month:02d}: {hours_in_month(year, month)} hours at $0.005 per address-hour")
    print(f"{'step':<84} {'addresses':>9} {'USD/month':>10}")
    for name, n, cost in rows:
        print(f"{name:<84} {n:>9} {cost:>10}")
    return rows


if __name__ == "__main__":
    main()
