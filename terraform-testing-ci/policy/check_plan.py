"""A policy gate over a Terraform or OpenTofu plan.

    terraform plan -out tfplan && terraform show -json tfplan > plan.json
    python check_plan.py plan.json

Reads the machine-readable plan and refuses it when an S3 bucket would be created without the
organisation's controls, or when a bucket that holds clinical data would be destroyed.
Exit code 0: no findings. 1: findings. 2: the plan could not be read.
"""
from __future__ import annotations

import json
import sys

BUCKET = "aws_s3_bucket"
ENCRYPTION = "aws_s3_bucket_server_side_encryption_configuration"
PUBLIC_ACCESS = "aws_s3_bucket_public_access_block"
VERSIONING = "aws_s3_bucket_versioning"
PUBLIC_ACCESS_SETTINGS = ("block_public_acls", "block_public_policy", "ignore_public_acls", "restrict_public_buckets")


def configured_resources(module: dict, prefix: str = "") -> dict[str, dict]:
    """Every resource in the configuration, by full address, with the module prefix it lives under."""
    found = {}
    for resource in module.get("resources", []):
        found[prefix + resource["address"]] = {"prefix": prefix, "expressions": resource.get("expressions", {})}
    for name, call in module.get("module_calls", {}).items():
        found.update(configured_resources(call.get("module", {}), f"{prefix}module.{name}."))
    return found


def companions(plan: dict) -> dict[str, dict[str, dict]]:
    """For each bucket address: the planned companion resources that refer to it, by type."""
    config = configured_resources(plan.get("configuration", {}).get("root_module", {}))
    planned = {change["address"]: change for change in plan.get("resource_changes", [])}
    linked: dict[str, dict[str, dict]] = {}
    for address, resource in config.items():
        references = resource["expressions"].get("bucket", {}).get("references", [])
        for reference in references:
            target = resource["prefix"] + reference
            if target in planned and planned[target]["type"] == BUCKET and address in planned:
                linked.setdefault(target, {})[planned[address]["type"]] = planned[address]["change"].get("after") or {}
    return linked


def first(blocks: object) -> dict:
    return blocks[0] if isinstance(blocks, list) and blocks else {}


def check(plan: dict) -> list[str]:
    findings: list[str] = []
    linked = companions(plan)
    for change in plan.get("resource_changes", []):
        if change["type"] != BUCKET:
            continue
        address, actions = change["address"], change["change"]["actions"]
        before, after = change["change"].get("before") or {}, change["change"].get("after") or {}

        if "delete" in actions and (before.get("tags") or {}).get("data-classification") == "clinical":
            findings.append(f"{address}: the plan destroys a bucket classified as clinical. This needs a signed-off change, not a merge.")
        if "create" not in actions and "update" not in actions:
            continue

        tags = after.get("tags") or {}
        if after.get("force_destroy") and tags.get("data-classification") == "clinical":
            findings.append(f"{address}: force_destroy is on for a bucket classified as clinical.")

        with_bucket = linked.get(address, {})
        default = first(first(with_bucket.get(ENCRYPTION, {}).get("rule")).get("apply_server_side_encryption_by_default"))
        if ENCRYPTION not in with_bucket:
            findings.append(f"{address}: no default encryption is configured.")
        elif default.get("sse_algorithm") != "aws:kms":
            findings.append(f"{address}: default encryption is {default.get('sse_algorithm')}, not aws:kms with a customer-managed key.")

        if PUBLIC_ACCESS not in with_bucket:
            findings.append(f"{address}: no public access block is configured.")
        else:
            off = [setting for setting in PUBLIC_ACCESS_SETTINGS if with_bucket[PUBLIC_ACCESS].get(setting) is not True]
            if off:
                findings.append(f"{address}: public access block leaves {', '.join(off)} off.")

        status = first(with_bucket.get(VERSIONING, {}).get("versioning_configuration")).get("status")
        if status != "Enabled":
            findings.append(f"{address}: versioning is not enabled.")
    return findings


def main() -> int:
    try:
        with open(sys.argv[1], encoding="utf-8") as handle:
            plan = json.load(handle)
        if "resource_changes" not in plan:
            raise ValueError("no resource_changes: is this the output of 'show -json' for a plan?")
    except (IndexError, OSError, ValueError) as error:
        print(f"Could not read the plan: {error}", file=sys.stderr)
        return 2
    findings = check(plan)
    for finding in findings:
        print(f"DENY  {finding}")
    buckets = sum(1 for change in plan["resource_changes"] if change["type"] == BUCKET)
    print(f"{buckets} bucket(s) in the plan, {len(findings)} finding(s)")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
