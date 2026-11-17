"""Lists every Lambda function version still on a runtime that Amazon Linux 1 retirement removes.

    python find_go1x.py --regions eu-west-1 us-east-1 [--profile name] [--csv out.csv]

Looks at $LATEST and every published version, because an alias can point at an old version long after
$LATEST has moved on. Read-only: it calls lambda:ListFunctions and lambda:ListAliases and nothing else.
"""
from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import asdict, dataclass

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

# Runtimes on Amazon Linux 1, deprecated together on 8 January 2024.
AL1_RUNTIMES = {"go1.x": "provided.al2023", "provided": "provided.al2023", "java8": "java8.al2"}
RETRY = Config(retries={"mode": "adaptive", "max_attempts": 10})


@dataclass(frozen=True)
class Finding:
    region: str
    function: str
    version: str
    runtime: str
    handler: str
    architectures: str
    aliases: str
    replacement: str


def aliases_by_version(client, name: str) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for page in client.get_paginator("list_aliases").paginate(FunctionName=name):
        for alias in page["Aliases"]:
            found.setdefault(alias["FunctionVersion"], []).append(alias["Name"])
    return found


def scan_region(session: boto3.Session, region: str) -> list[Finding]:
    client = session.client("lambda", region_name=region, config=RETRY)
    findings: list[Finding] = []
    alias_cache: dict[str, dict[str, list[str]]] = {}
    for page in client.get_paginator("list_functions").paginate(FunctionVersion="ALL"):
        for fn in page["Functions"]:
            runtime = fn.get("Runtime", "")          # container image functions have no Runtime
            if runtime not in AL1_RUNTIMES:
                continue
            name = fn["FunctionName"]
            if name not in alias_cache:
                alias_cache[name] = aliases_by_version(client, name)
            findings.append(Finding(
                region=region, function=name, version=fn["Version"], runtime=runtime,
                handler=fn.get("Handler", ""), architectures=",".join(fn.get("Architectures", ["x86_64"])),
                aliases=",".join(sorted(alias_cache[name].get(fn["Version"], []))),
                replacement=AL1_RUNTIMES[runtime],
            ))
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--regions", nargs="+", required=True)
    parser.add_argument("--profile")
    parser.add_argument("--csv")
    args = parser.parse_args(argv)
    session = boto3.Session(profile_name=args.profile) if args.profile else boto3.Session()

    findings: list[Finding] = []
    failed = False
    for region in args.regions:
        try:
            findings.extend(scan_region(session, region))
        except ClientError as err:
            failed = True
            print(f"{region}: {err.response['Error']['Code']}: {err.response['Error']['Message']}", file=sys.stderr)

    rows = [asdict(f) for f in findings]
    if args.csv:
        with open(args.csv, "w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(Finding.__dataclass_fields__))
            writer.writeheader()
            writer.writerows(rows)
    for f in findings:
        alias = f" (aliases: {f.aliases})" if f.aliases else ""
        print(f"{f.region}  {f.function}:{f.version}  {f.runtime} -> {f.replacement}{alias}")
    print(f"{len(findings)} function versions on Amazon Linux 1 runtimes", file=sys.stderr)
    return 2 if failed else (1 if findings else 0)


if __name__ == "__main__":
    sys.exit(main())
