"""A made-up fleet of eight EKS clusters, audited in moto, and three plans priced
over the first twelve months of extended support billing (April 2024 to March 2025).

    python tools/demo_fleet.py
"""
from __future__ import annotations

import json
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import boto3  # noqa: E402
from moto import mock_aws  # noqa: E402

from eks_support.audit import audit_account  # noqa: E402
from eks_support.cost import month_cost, months  # noqa: E402
from eks_support.upgrade_path import steps  # noqa: E402

TODAY = date(2024, 2, 24)
FLEET = {
    "eu-west-1": [("payments-prod", "1.24"), ("payments-staging", "1.24"), ("data-prod", "1.25"), ("platform-tools", "1.26")],
    "us-east-1": [("web-prod", "1.27"), ("web-dev", "1.28"), ("sandbox", "1.23"), ("new-svc", "1.29")],
}
BILLED = months(date(2024, 4, 1), 12)


def year_cost(version: str) -> Decimal:
    return sum((month_cost(version, y, m) for y, m in BILLED), Decimal(0))


def main() -> dict:
    with mock_aws():
        session = boto3.Session(region_name="eu-west-1", aws_access_key_id="testing", aws_secret_access_key="testing")
        for region, clusters in FLEET.items():
            eks = session.client("eks", region_name=region)
            for name, version in clusters:
                eks.create_cluster(name=name, version=version, roleArn="arn:aws:iam::123456789012:role/eks",
                                   resourcesVpcConfig={"subnetIds": ["subnet-1"]})
        reports = audit_account(session, list(FLEET), TODAY, with_insights=False)

    print(f"Audit on {TODAY}")
    print(f"{'cluster':<18} {'region':<10} {'ver':<5} {'status':<9} {'extended from':<14} {'steps':>5} {'Apr 24-Mar 25':>14}")
    for r in sorted(reports, key=lambda r: r.version):
        print(f"{r.name:<18} {r.region:<10} {r.version:<5} {r.status:<9} {r.extended_from or '-':<14} "
              f"{r.steps_to_latest:>5} {year_cost(r.version):>14}")

    plans = {
        "Leave every cluster where it is": sum((year_cost(r.version) for r in reports), Decimal(0)),
        "Upgrade 1.23 and 1.24 to 1.25 by 31 March": sum((year_cost("1.25" if r.version in ("1.23", "1.24") else r.version)
                                                          for r in reports), Decimal(0)),
        "Every cluster on 1.29 by 31 March": year_cost("1.29") * len(reports),
    }
    print("\nPlans, control plane only, April 2024 to March 2025")
    for name, total in plans.items():
        print(f"  {name:<46} ${total:>9}")
    print("\nOne cluster, April 2024 to March 2025, by the version it runs from 1 April")
    for version in ("1.24", "1.25", "1.26", "1.27", "1.28", "1.29"):
        # a whole month in standard support is at most 744 h x $0.10 = $74.40
        extended_months = sum(1 for y, m in BILLED if month_cost(version, y, m) > Decimal("74.40"))
        print(f"  {version}  ${year_cost(version):>8}   months with extended support charges: {extended_months}")
    print("\nUpgrade steps from 1.24 to 1.29")
    for step in steps("1.24", "1.29"):
        print(f"  -> {step['to']}: " + ("; ".join(step["removed"]) or "no API removals"))
    return {"plans": {k: str(v) for k, v in plans.items()}, "clusters": [r.__dict__ for r in reports]}


if __name__ == "__main__":
    result = main()
    if len(sys.argv) > 1:
        Path(sys.argv[1]).write_text(json.dumps(result, indent=2, default=str))
