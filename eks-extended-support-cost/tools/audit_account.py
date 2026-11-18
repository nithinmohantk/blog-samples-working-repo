"""Audit the EKS clusters in your account: support status, upgrade steps, 12-month cost outlook.

    python tools/audit_account.py --regions eu-west-1 us-east-1 --out eks.json
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import boto3  # noqa: E402

from eks_support.audit import audit_account  # noqa: E402

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--regions", nargs="+", required=True)
    parser.add_argument("--today", type=date.fromisoformat, default=date.today())
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    reports = audit_account(boto3.Session(), args.regions, args.today)
    text = json.dumps([r.__dict__ for r in reports], indent=2)
    (args.out.write_text(text) if args.out else print(text))
