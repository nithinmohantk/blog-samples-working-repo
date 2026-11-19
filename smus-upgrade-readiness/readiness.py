"""Read-only upgrade-readiness report for a SageMaker AI domain.

Before upgrading a SageMaker AI domain into SageMaker Unified Studio, this
script inventories what the domain uses (Studio Classic apps, custom images,
lifecycle configurations, VPC-only networking, Canvas, RStudio) and lists the
items to review. It never changes the domain.

Usage:
    python readiness.py --domain-id d-xxxxxxxxxxxx --region eu-west-1
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import asdict, dataclass, field
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger("smus-readiness")

# Studio Classic ran notebooks as JupyterServer and KernelGateway apps.
CLASSIC_APP_TYPES = {"JupyterServer", "KernelGateway"}
ACTIVE_APP_STATUSES = {"InService", "Pending", "Updating"}


@dataclass
class Finding:
    severity: str  # "blocker", "review" or "info"
    area: str
    detail: str


@dataclass
class Inventory:
    domain_id: str
    domain_name: str
    auth_mode: str
    network_access: str
    default_landing_uri: str | None
    studio_web_portal: str | None
    unified_studio_settings: dict[str, Any] | None
    user_profiles: list[str] = field(default_factory=list)
    spaces: list[str] = field(default_factory=list)
    apps_by_type: dict[str, int] = field(default_factory=dict)
    custom_images: list[str] = field(default_factory=list)
    lifecycle_config_arns: list[str] = field(default_factory=list)


def make_client(region: str):
    # Adaptive retries absorb throttling on large domains with many apps.
    cfg = Config(region_name=region, retries={"mode": "adaptive", "max_attempts": 10})
    return boto3.client("sagemaker", config=cfg)


def _paginate(client, operation: str, key: str, **kwargs) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for page in client.get_paginator(operation).paginate(**kwargs):
        items.extend(page.get(key, []))
    return items


def collect(client, domain_id: str) -> Inventory:
    domain = client.describe_domain(DomainId=domain_id)
    user_settings = domain.get("DefaultUserSettings", {})
    jupyterlab = user_settings.get("JupyterLabAppSettings", {})
    kernel_gw = user_settings.get("KernelGatewayAppSettings", {})

    images = [
        img["AppImageConfigName"]
        for img in jupyterlab.get("CustomImages", []) + kernel_gw.get("CustomImages", [])
    ]
    lifecycle = list(
        dict.fromkeys(
            jupyterlab.get("LifecycleConfigArns", []) + kernel_gw.get("LifecycleConfigArns", [])
        )
    )

    apps = _paginate(client, "list_apps", "Apps", DomainIdEquals=domain_id)
    apps_by_type: dict[str, int] = {}
    for app in apps:
        if app.get("Status") in ACTIVE_APP_STATUSES:
            apps_by_type[app["AppType"]] = apps_by_type.get(app["AppType"], 0) + 1

    return Inventory(
        domain_id=domain_id,
        domain_name=domain.get("DomainName", ""),
        auth_mode=domain.get("AuthMode", ""),
        network_access=domain.get("AppNetworkAccessType", "PublicInternetOnly"),
        default_landing_uri=user_settings.get("DefaultLandingUri"),
        studio_web_portal=user_settings.get("StudioWebPortal"),
        unified_studio_settings=domain.get("DomainSettings", {}).get("UnifiedStudioSettings"),
        user_profiles=[
            p["UserProfileName"]
            for p in _paginate(client, "list_user_profiles", "UserProfiles", DomainIdEquals=domain_id)
        ],
        spaces=[
            s["SpaceName"] for s in _paginate(client, "list_spaces", "Spaces", DomainIdEquals=domain_id)
        ],
        apps_by_type=apps_by_type,
        custom_images=sorted(set(images)),
        lifecycle_config_arns=lifecycle,
    )


def assess(inv: Inventory) -> list[Finding]:
    findings: list[Finding] = []

    if inv.unified_studio_settings and inv.unified_studio_settings.get("ProjectId"):
        findings.append(Finding("info", "status", "Domain is already linked to a Unified Studio project."))

    classic = {t: n for t, n in inv.apps_by_type.items() if t in CLASSIC_APP_TYPES}
    landing = inv.default_landing_uri or ""
    if classic or landing.startswith("app:JupyterServer"):
        findings.append(Finding(
            "blocker", "studio-classic",
            f"Studio Classic is still in use (active apps: {classic or 'none'}, "
            f"default landing: {landing or 'unset'}). Migrate the domain from Studio Classic "
            "to Studio first; the Unified Studio upgrade starts from SageMaker Studio.",
        ))

    if inv.network_access == "VpcOnly":
        findings.append(Finding(
            "review", "network",
            "Domain runs in VPC-only mode. Confirm the subnets and VPC endpoints the Unified "
            "Studio project will use before moving users.",
        ))

    if inv.custom_images:
        findings.append(Finding(
            "review", "images",
            f"Custom images attached: {', '.join(inv.custom_images)}. Launch each one in a test "
            "space from Unified Studio before migrating the users who depend on it.",
        ))

    if inv.lifecycle_config_arns:
        findings.append(Finding(
            "review", "lifecycle",
            f"{len(inv.lifecycle_config_arns)} lifecycle configuration(s) attached. Run them in a "
            "test space; prefer moving package installs into the image.",
        ))

    for app_type in ("Canvas", "RStudioServerPro", "RSessionGateway"):
        if inv.apps_by_type.get(app_type):
            findings.append(Finding(
                "review", app_type.lower(),
                f"{inv.apps_by_type[app_type]} active {app_type} app(s). Check how these users will "
                "reach the tool after the upgrade before disabling Studio access.",
            ))

    findings.append(Finding(
        "info", "scope",
        f"{len(inv.user_profiles)} user profile(s) and {len(inv.spaces)} space(s) would be imported.",
    ))
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--domain-id", required=True)
    parser.add_argument("--region", required=True)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    try:
        inv = collect(make_client(args.region), args.domain_id)
    except ClientError as exc:
        logger.error("AWS error: %s", exc.response.get("Error", {}).get("Message", exc))
        return 2
    except BotoCoreError as exc:
        logger.error("SDK error: %s", exc)
        return 2

    findings = assess(inv)
    json.dump({"inventory": asdict(inv), "findings": [asdict(f) for f in findings]},
              sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")
    return 1 if any(f.severity == "blocker" for f in findings) else 0


if __name__ == "__main__":
    sys.exit(main())
