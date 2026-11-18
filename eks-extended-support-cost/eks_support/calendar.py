"""The Amazon EKS Kubernetes version calendar as published on 23 February 2024.

Sources: the EKS release calendar in the user guide and the AWS Containers blog
post "Amazon EKS extended support for Kubernetes versions pricing" (16 January 2024).
Where AWS published only a month, the date is the first of that month and
`month_only` is True: treat those as "no later than", and check the calendar
again before planning to the day.

The EKS API (botocore 1.34.49) has no field that says whether a cluster's
version is in standard or extended support, so this table is the only source.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class VersionDates:
    version: str
    eks_release: date
    end_of_standard: date
    end_of_extended: date | None  # None: version not eligible for extended support
    month_only: bool = False


CALENDAR = {v.version: v for v in (
    VersionDates("1.23", date(2022, 8, 11), date(2023, 10, 11), date(2024, 10, 11)),
    VersionDates("1.24", date(2022, 11, 15), date(2024, 1, 31), date(2025, 1, 31)),
    VersionDates("1.25", date(2023, 2, 21), date(2024, 5, 1), date(2025, 5, 1), month_only=True),
    VersionDates("1.26", date(2023, 4, 11), date(2024, 6, 1), date(2025, 6, 1), month_only=True),
    VersionDates("1.27", date(2023, 5, 24), date(2024, 7, 1), date(2025, 7, 1), month_only=True),
    VersionDates("1.28", date(2023, 9, 26), date(2024, 11, 1), date(2025, 11, 1), month_only=True),
    VersionDates("1.29", date(2024, 1, 23), date(2025, 3, 1), date(2026, 3, 1), month_only=True),
)}

LATEST = "1.29"


def support_status(version: str, on: date) -> str:
    """'standard', 'extended', 'ended' or 'unknown' for a version on a given day."""
    dates = CALENDAR.get(version)
    if dates is None:
        return "unknown"
    if on < dates.end_of_standard:
        return "standard"
    if dates.end_of_extended and on < dates.end_of_extended:
        return "extended"
    return "ended"
