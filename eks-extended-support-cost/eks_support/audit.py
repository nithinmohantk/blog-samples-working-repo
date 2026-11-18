"""List every EKS cluster in an account, with its support status and cost outlook.

Read-only: eks:ListClusters, eks:DescribeCluster and, where available,
eks:ListInsights for upgrade readiness. Nothing is changed.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date

from botocore.exceptions import ClientError

from .calendar import CALENDAR, LATEST, support_status
from .cost import first_extended_day, forecast
from .upgrade_path import steps

log = logging.getLogger("eks_support")


@dataclass
class ClusterReport:
    region: str
    name: str
    version: str
    status: str
    extended_from: str | None
    steps_to_latest: int
    next_12_months: dict[str, str]
    total_12_months: str
    insights: list[dict] = field(default_factory=list)


def upgrade_insights(eks, name: str) -> list[dict]:
    """Upgrade-readiness insights that are not passing (EKS upgrade insights, GA 20 December 2023)."""
    found = []
    try:
        pages = eks.get_paginator("list_insights").paginate(
            clusterName=name, filter={"categories": ["UPGRADE_READINESS"]})
        for page in pages:
            for item in page.get("insights", []):
                status = (item.get("insightStatus") or {}).get("status")
                if status != "PASSING":
                    found.append({"name": item.get("name"), "kubernetesVersion": item.get("kubernetesVersion"),
                                  "status": status})
    except (ClientError, NotImplementedError) as err:  # older SDK mocks, missing permission
        found.append({"name": "insights unavailable", "status": str(err).split(":")[-1].strip()[:80]})
    return found


def audit_region(eks, region: str, today: date, with_insights: bool = True) -> list[ClusterReport]:
    reports = []
    for page in eks.get_paginator("list_clusters").paginate():
        for name in page["clusters"]:
            cluster = eks.describe_cluster(name=name)["cluster"]
            version = cluster["version"]
            outlook = forecast(version, today)
            extended = first_extended_day(version, today) if version in CALENDAR else None
            reports.append(ClusterReport(
                region=region, name=name, version=version,
                status=support_status(version, today),
                extended_from=extended.isoformat() if extended else None,
                steps_to_latest=len(steps(version, LATEST)) if version in CALENDAR else -1,
                next_12_months={k: str(v) for k, v in outlook.items()},
                total_12_months=str(sum(outlook.values())),
                insights=upgrade_insights(eks, name) if with_insights else [],
            ))
    log.info("region=%s clusters=%d", region, len(reports))
    return reports


def audit_account(session, regions: list[str], today: date, with_insights: bool = True) -> list[ClusterReport]:
    out = []
    for region in regions:
        try:
            out.extend(audit_region(session.client("eks", region_name=region), region, today, with_insights))
        except ClientError as err:
            log.warning("region=%s skipped: %s", region, err)
    return out
