"""Audit public IPv4 addresses across an account and price them.

    python tools/audit_account.py --out ipv4.csv                 # every enabled Region
    python tools/audit_account.py --regions eu-west-1 us-east-1 --month 2024-02

Needs ec2:DescribeRegions, DescribeAddresses, DescribeInstances,
DescribeNetworkInterfaces and DescribeNatGateways. Nothing is changed.
Site-to-Site VPN tunnels and Global Accelerator addresses are not covered;
use VPC IPAM Public IP Insights or the CUR for those.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import boto3  # noqa: E402

from ipv4_audit.audit import audit_account  # noqa: E402
from ipv4_audit.cost import summarise  # noqa: E402


def main(argv: list[str] | None = None, session=None) -> dict:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--regions", nargs="*", help="default: every enabled Region")
    parser.add_argument("--month", default="2024-02", help="month to price, YYYY-MM (default 2024-02)")
    parser.add_argument("--out", type=Path, help="write one row per address to this CSV")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

    year, month = (int(part) for part in args.month.split("-"))
    addresses = audit_account(session or boto3.Session(), args.regions)
    if args.out:
        with args.out.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(addresses[0].as_row()) if addresses else ["ip"])
            writer.writeheader()
            writer.writerows(a.as_row() for a in addresses)
    summary = summarise(addresses, year, month)
    print(json.dumps(summary, indent=2))
    return summary


if __name__ == "__main__":
    main()
