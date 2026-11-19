"""python -m horizondb_readiness "postgresql://..." [--geo-replica] [--vnet-injection] [--cmk-geo-backup]

Exit code 0: no blockers. 2: at least one blocker. 1: could not connect.
"""
from __future__ import annotations

import argparse
import json
import sys

import psycopg

from .checks import Severity, assess, summary
from .collect import collect


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="horizondb_readiness")
    p.add_argument("conninfo", help="libpq connection string or URI for the source database")
    p.add_argument("--geo-replica", action="store_true", help="the source uses a cross-region read replica")
    p.add_argument("--vnet-injection", action="store_true", help="network design requires VNet injection")
    p.add_argument("--cmk-geo-backup", action="store_true", help="policy requires CMK and geo-redundant backup")
    p.add_argument("--retention-days", type=int, default=7)
    p.add_argument("--peak-connections", type=int, help="peak client connections from monitoring")
    p.add_argument("--json", action="store_true")
    a = p.parse_args(argv)

    inventory = dict(uses_geo_replica=a.geo_replica, needs_vnet_injection=a.vnet_injection,
                     needs_cmk_and_geo_backup=a.cmk_geo_backup, backup_retention_days=a.retention_days)
    if a.peak_connections is not None:
        inventory["peak_connections"] = a.peak_connections
    try:
        facts = collect(a.conninfo, **inventory)
    except psycopg.OperationalError as e:
        print(f"could not connect: {e}", file=sys.stderr)
        return 1

    findings = assess(facts)
    if a.json:
        print(json.dumps({"summary": summary(findings),
                          "findings": [dict(severity=x.severity.value, code=x.code, message=x.message) for x in findings]},
                         indent=2))
    else:
        for x in findings:
            print(f"[{x.severity.value.upper():7}] {x.code}: {x.message}")
        print(summary(findings))
    return 2 if any(x.severity is Severity.BLOCKER for x in findings) else 0


if __name__ == "__main__":
    sys.exit(main())
