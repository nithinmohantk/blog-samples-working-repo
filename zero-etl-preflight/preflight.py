"""Pre-flight checks and setup for an Aurora zero-ETL integration with Amazon Redshift.

check_parameters()  compares an Aurora DB cluster parameter group with the values
                    zero-ETL requires, so a missing setting is found before the
                    integration fails.
data_filter()       builds a data filter expression in the documented syntax.
target_policy()     builds the Redshift resource policy that authorizes the
                    source cluster and lets the account create the integration.
create()            authorizes the source on the Redshift namespace and creates
                    the integration, treating an existing one as success.
NO_PK_SQL           lists Aurora PostgreSQL tables without a primary key, which
                    zero-ETL puts in a failed state.
"""

from __future__ import annotations

import json
import re
from typing import Any

REQUIRED = {
    "aurora-mysql": {
        "aurora_enhanced_binlog": "1",
        "binlog_backup": "0",
        "binlog_format": "ROW",
        "binlog_replication_globaldb": "0",
        "binlog_row_image": "full",
        "binlog_row_metadata": "full",
    },
    "aurora-postgresql": {
        "rds.logical_replication": "1",
        "aurora.enhanced_logical_replication": "1",
        "aurora.logical_replication_backup": "0",
        "aurora.logical_replication_globaldb": "0",
    },
}
FORBIDDEN = {  # aurora-mysql settings that must not have these values
    "binlog_transaction_compression": "ON",
    "binlog_row_value_options": "PARTIAL_JSON",
}
MAX_PATTERNS = 99
MAX_PATTERN_LENGTH = 256

NO_PK_SQL = """
SELECT n.nspname AS table_schema, c.relname AS table_name
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind IN ('r', 'p')
  AND NOT c.relispartition
  AND n.nspname NOT IN ('pg_catalog', 'information_schema')
  AND n.nspname NOT LIKE 'pg_toast%'
  AND NOT EXISTS (
        SELECT 1 FROM pg_constraint k
        WHERE k.conrelid = c.oid AND k.contype = 'p')
ORDER BY 1, 2;
"""


def cluster_parameters(rds: Any, group: str) -> dict[str, str | None]:
    """Name to value for every parameter in a DB cluster parameter group."""
    values: dict[str, str | None] = {}
    for page in rds.get_paginator("describe_db_cluster_parameters").paginate(
            DBClusterParameterGroupName=group):
        for p in page["Parameters"]:
            values[p["ParameterName"]] = p.get("ParameterValue")
    return values


def check_parameters(engine: str, values: dict[str, str | None]) -> list[str]:
    if engine not in REQUIRED:
        raise ValueError(f"engine must be one of {sorted(REQUIRED)}")
    problems = [f"{name} is {values.get(name)!r}, must be {want!r}"
                for name, want in REQUIRED[engine].items()
                if str(values.get(name) or "").lower() != want.lower()]
    if engine == "aurora-mysql":
        problems += [f"{name} must not be {bad!r}" for name, bad in FORBIDDEN.items()
                     if str(values.get(name) or "").upper() == bad]
    return problems


def data_filter(engine: str, include: list[str], exclude: list[str] = ()) -> str:
    """Filter expression, broadest includes first and excludes after, as AWS recommends."""
    parts = 3 if engine == "aurora-postgresql" else 2
    patterns = [("include", p) for p in include] + [("exclude", p) for p in exclude]
    if engine == "aurora-postgresql" and not include:
        raise ValueError("Aurora PostgreSQL needs at least one include pattern, such as mydb.*.*")
    if len(patterns) > MAX_PATTERNS:
        raise ValueError(f"{len(patterns)} patterns; the limit is {MAX_PATTERNS}")
    for _, p in patterns:
        if len(p) > MAX_PATTERN_LENGTH:
            raise ValueError(f"pattern longer than {MAX_PATTERN_LENGTH} characters: {p[:40]}...")
        # Split on dots outside /regex/ sections to count name parts.
        names = re.findall(r"/[^/]*/|[^.]+", p)
        if len(names) != parts:
            raise ValueError(f"{p!r}: expected {'database.schema.table' if parts == 3 else 'database.table'}")
        if engine == "aurora-postgresql" and names[0].startswith("/"):
            raise ValueError(f"{p!r}: Aurora PostgreSQL does not allow a regular expression for the database")
    return ", ".join(f"{kind}: {p}" for kind, p in patterns)


def target_policy(source_arn: str, account_id: str, namespace_arn: str) -> dict[str, Any]:
    return {
        "Version": "2012-10-17",
        "Statement": [
            {"Effect": "Allow", "Principal": {"Service": "redshift.amazonaws.com"},
             "Action": "redshift:AuthorizeInboundIntegration", "Resource": namespace_arn,
             "Condition": {"StringEquals": {"aws:SourceArn": source_arn}}},
            {"Effect": "Allow", "Principal": {"AWS": f"arn:aws:iam::{account_id}:root"},
             "Action": "redshift:CreateInboundIntegration", "Resource": namespace_arn},
        ],
    }


def create(rds: Any, redshift: Any, *, name: str, source_arn: str, namespace_arn: str,
           account_id: str, kms_key_id: str | None = None, data_filter_expr: str | None = None) -> str:
    redshift.put_resource_policy(ResourceArn=namespace_arn,
                                 Policy=json.dumps(target_policy(source_arn, account_id, namespace_arn)))
    kwargs: dict[str, Any] = {"SourceArn": source_arn, "TargetArn": namespace_arn, "IntegrationName": name}
    if kms_key_id:
        kwargs["KMSKeyId"] = kms_key_id
    if data_filter_expr:
        kwargs["DataFilter"] = data_filter_expr
    try:
        return rds.create_integration(**kwargs)["IntegrationArn"]
    except rds.exceptions.IntegrationAlreadyExistsFault:
        for page in rds.get_paginator("describe_integrations").paginate():
            for i in page["Integrations"]:
                if i["IntegrationName"] == name:
                    return i["IntegrationArn"]
        raise
