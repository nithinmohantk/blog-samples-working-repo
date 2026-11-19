"""Turns facts about a source PostgreSQL database into findings for a move to HorizonDB.

Pure functions only: collecting the facts is in collect.py, so the rules can be
tested without a database.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .catalog import (
    BUILTIN_EXTENSIONS,
    HORIZONDB_EXTENSIONS,
    HORIZONDB_MAJOR_VERSIONS,
    HORIZONDB_UNSUPPORTED_EXTENSIONS,
    NOT_AVAILABLE_AT_GA,
)


class Severity(str, Enum):
    BLOCKER = "blocker"  # must change before the move
    ACTION = "action"    # move is possible, but plan for this
    INFO = "info"


@dataclass(frozen=True)
class Finding:
    severity: Severity
    code: str
    message: str


@dataclass
class SourceFacts:
    server_version_num: int                      # e.g. 160002
    extensions: dict[str, str]                   # name -> installed version
    logical_slots: int = 0
    tables_without_pk: list[str] = field(default_factory=list)
    database_bytes: int = 0
    max_connections: int = 100
    peak_connections: int = 0                    # highest observed, from monitoring or pg_stat_activity
    uses_geo_replica: bool = False               # from your inventory, not detectable in SQL
    needs_vnet_injection: bool = False
    needs_cmk_and_geo_backup: bool = False
    backup_retention_days: int = 7

    @property
    def major(self) -> int:
        return self.server_version_num // 10000


def _version_tuple(v: str) -> tuple[int, ...]:
    parts = []
    for p in v.split("."):
        digits = "".join(ch for ch in p if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def assess(f: SourceFacts) -> list[Finding]:
    out: list[Finding] = []

    status = HORIZONDB_MAJOR_VERSIONS.get(f.major)
    if status is None:
        supported = ", ".join(f"{m} ({s})" for m, s in sorted(HORIZONDB_MAJOR_VERSIONS.items()))
        out.append(Finding(Severity.BLOCKER, "major_version",
                           f"PostgreSQL {f.major} is not offered; HorizonDB offers {supported}. "
                           "Test the application on 17 first, then migrate with dump/restore or logical replication."))
    elif status == "preview":
        out.append(Finding(Severity.ACTION, "major_version",
                           f"PostgreSQL {f.major} is in preview on HorizonDB; use 17 for production."))

    for name, installed in sorted(f.extensions.items()):
        if name in BUILTIN_EXTENSIONS:
            continue
        if name in HORIZONDB_UNSUPPORTED_EXTENSIONS or name not in HORIZONDB_EXTENSIONS:
            out.append(Finding(Severity.BLOCKER, f"extension:{name}",
                               f"Extension {name} {installed} is not available on HorizonDB."))
            continue
        offered = HORIZONDB_EXTENSIONS[name]
        if offered and _version_tuple(installed) > _version_tuple(offered):
            out.append(Finding(Severity.ACTION, f"extension:{name}",
                               f"{name} {installed} is newer than HorizonDB's {offered}; check that the "
                               "features you use exist in the older version."))
        elif offered and _version_tuple(installed) < _version_tuple(offered):
            out.append(Finding(Severity.INFO, f"extension:{name}",
                               f"{name} {installed} will be {offered} on HorizonDB; review its release notes."))
        out.append(Finding(Severity.INFO, f"allowlist:{name}",
                           f"Add {name} to azure.extensions in the parameter group before CREATE EXTENSION."))

    if f.logical_slots:
        out.append(Finding(Severity.ACTION, "logical_slots",
                           f"{f.logical_slots} logical replication slot(s): recreate them on HorizonDB and "
                           "repoint consumers; pg_failover_slots is not available."))
    if f.tables_without_pk:
        sample = ", ".join(f.tables_without_pk[:5])
        more = f" and {len(f.tables_without_pk) - 5} more" if len(f.tables_without_pk) > 5 else ""
        out.append(Finding(Severity.ACTION, "no_primary_key",
                           f"{len(f.tables_without_pk)} table(s) without a primary key ({sample}{more}): "
                           "UPDATE and DELETE cannot be replicated logically without one, so a low-downtime "
                           "migration needs a key or REPLICA IDENTITY FULL."))
    if f.peak_connections > 0.5 * f.max_connections:
        out.append(Finding(Severity.ACTION, "connection_pooling",
                           f"Peak {f.peak_connections} of {f.max_connections} connections. "
                           + NOT_AVAILABLE_AT_GA["connection_pooling"]))
    if f.uses_geo_replica:
        out.append(Finding(Severity.BLOCKER, "cross_region_readers", NOT_AVAILABLE_AT_GA["cross_region_readers"]))
    if f.needs_vnet_injection:
        out.append(Finding(Severity.BLOCKER, "vnet_injection", NOT_AVAILABLE_AT_GA["vnet_injection"]))
    if f.needs_cmk_and_geo_backup:
        out.append(Finding(Severity.BLOCKER, "cmk_with_geo_backup", NOT_AVAILABLE_AT_GA["cmk_with_geo_backup"]))
    if f.backup_retention_days > 35:
        out.append(Finding(Severity.BLOCKER, "long_term_retention", NOT_AVAILABLE_AT_GA["long_term_retention"]))
    return out


def summary(findings: list[Finding]) -> dict[str, int]:
    counts = {s.value: 0 for s in Severity}
    for x in findings:
        counts[x.severity.value] += 1
    return counts
