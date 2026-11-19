"""Lint Kubernetes manifests for a move to Amazon EKS Auto Mode.

Teams moving from managed node groups or self-managed Karpenter usually carry
manifests that Auto Mode handles differently. This script reads YAML files and
reports what has to change:

- Karpenter EC2NodeClass objects (Auto Mode uses eks.amazonaws.com/v1 NodeClass)
  and NodeClass fields Auto Mode does not offer (custom AMIs, user data, block
  device mappings).
- NodePools that reference the wrong node class, use karpenter.k8s.aws/*
  instance labels, request Windows, or set expireAfter above Auto Mode's
  21-day maximum node lifetime.
- StorageClasses on the self-managed EBS CSI provisioner, Ingresses using the
  deprecated class annotation, and workloads pinned to managed node groups.

It reads files only and needs no cluster access.
Exit code: 0 when there are no errors, 1 when there are, 2 on usage errors.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

import yaml

MAX_NODE_LIFETIME_HOURS = 21 * 24
UNSUPPORTED_NODECLASS_FIELDS = {
    "amiFamily": "Auto Mode nodes run an AWS-managed Bottlerocket-based AMI",
    "amiSelectorTerms": "custom AMIs are not supported",
    "userData": "user data is not supported; nodes cannot be customised at boot",
    "blockDeviceMappings": "use spec.ephemeralStorage (size, iops, throughput, kmsKeyID)",
    "metadataOptions": "instance metadata settings are managed by Auto Mode",
    "instanceStorePolicy": "not available in Auto Mode",
}
SUPPORTED_KARPENTER_AWS_LABELS = {"karpenter.k8s.aws/instance-tenancy"}
WORKLOAD_KINDS = {"Deployment", "StatefulSet", "DaemonSet", "Job", "ReplicaSet"}


@dataclass
class Finding:
    level: str  # ERROR or WARNING
    file: str
    obj: str
    message: str

    def __str__(self) -> str:
        return f"{self.level:<7} {self.file} {self.obj}: {self.message}"


def parse_hours(value: str) -> float | None:
    """Parse a Go duration such as '336h', '720h30m' or '90m' into hours. 'Never' -> inf."""
    if value == "Never":
        return float("inf")
    parts = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?", value or "")
    if not parts or not any(parts.groups()):
        return None
    h, m, s = (int(p) if p else 0 for p in parts.groups())
    return h + m / 60 + s / 3600


def _documents(path: Path) -> Iterator[dict[str, Any]]:
    for doc in yaml.safe_load_all(path.read_text(encoding="utf-8")):
        if isinstance(doc, dict) and doc.get("kind"):
            yield doc


def _pod_spec(doc: dict[str, Any]) -> dict[str, Any]:
    spec = doc.get("spec") or {}
    if doc["kind"] == "Pod":
        return spec
    template = spec.get("jobTemplate", {}).get("spec", spec) if doc["kind"] == "CronJob" else spec
    return (template.get("template") or {}).get("spec") or {}


def lint_document(doc: dict[str, Any], file: str) -> list[Finding]:
    kind, api = doc.get("kind"), doc.get("apiVersion", "")
    name = f"{kind}/{(doc.get('metadata') or {}).get('name', '?')}"
    spec = doc.get("spec") or {}
    out: list[Finding] = []

    def add(level: str, msg: str) -> None:
        out.append(Finding(level, file, name, msg))

    if kind == "EC2NodeClass" or api.startswith("karpenter.k8s.aws/"):
        add("ERROR", "Karpenter EC2NodeClass is not used by Auto Mode; create an eks.amazonaws.com/v1 NodeClass")

    if kind == "NodeClass" and api.startswith("eks.amazonaws.com/"):
        for field_name, why in UNSUPPORTED_NODECLASS_FIELDS.items():
            if field_name in spec:
                add("ERROR", f"spec.{field_name} is not supported: {why}")
        if "role" in spec and "instanceProfile" in spec:
            add("ERROR", "spec.role and spec.instanceProfile are mutually exclusive")
        for required in ("subnetSelectorTerms", "securityGroupSelectorTerms"):
            if not spec.get(required):
                add("ERROR", f"spec.{required} is required")

    if kind == "NodePool":
        template = (spec.get("template") or {}).get("spec") or {}
        ref = template.get("nodeClassRef") or {}
        if (ref.get("group"), ref.get("kind")) != ("eks.amazonaws.com", "NodeClass"):
            add("ERROR", "nodeClassRef must be group eks.amazonaws.com, kind NodeClass")
        if ref.get("name") == "default" and (doc.get("metadata") or {}).get("name") in {"system", "general-purpose"}:
            add("WARNING", "this looks like a built-in NodePool; do not edit built-in pools, create your own")
        for req in template.get("requirements") or []:
            key = req.get("key", "")
            if key.startswith("karpenter.k8s.aws/") and key not in SUPPORTED_KARPENTER_AWS_LABELS:
                add("ERROR", f"requirement {key} is not used by Auto Mode; use eks.amazonaws.com/{key.split('/', 1)[1]}")
            if key in {"kubernetes.io/os", "node.kubernetes.io/windows-build"}:
                add("ERROR", f"requirement {key} is not supported; Auto Mode runs Linux nodes only")
        expire = template.get("expireAfter")
        if expire is not None:
            hours = parse_hours(str(expire))
            if hours is None:
                add("ERROR", f"expireAfter {expire!r} is not a valid duration")
            elif hours > MAX_NODE_LIFETIME_HOURS:
                add("ERROR", f"expireAfter {expire} exceeds Auto Mode's 21-day (504h) maximum node lifetime")

    if kind == "StorageClass" and doc.get("provisioner") == "ebs.csi.aws.com":
        add("WARNING", "provisioner ebs.csi.aws.com is the self-managed EBS CSI driver; Auto Mode volumes use ebs.csi.eks.amazonaws.com")

    if kind == "IngressClass" and spec.get("controller") == "ingress.k8s.aws/alb":
        add("WARNING", "controller ingress.k8s.aws/alb is the self-managed Load Balancer Controller; Auto Mode uses eks.amazonaws.com/alb")
    if kind == "IngressClassParams" and api.startswith("elbv2.k8s.aws/"):
        add("WARNING", "IngressClassParams moves from elbv2.k8s.aws/v1beta1 to eks.amazonaws.com/v1, with renamed fields")
    if kind == "Ingress":
        annotations = (doc.get("metadata") or {}).get("annotations") or {}
        if "kubernetes.io/ingress.class" in annotations:
            add("ERROR", "kubernetes.io/ingress.class is not supported; set spec.ingressClassName")
        if "alb.ingress.kubernetes.io/group.name" in annotations:
            add("ERROR", "alb.ingress.kubernetes.io/group.name is not supported; define groups in IngressClassParams")

    if kind in WORKLOAD_KINDS | {"Pod", "CronJob"}:
        selector = _pod_spec(doc).get("nodeSelector") or {}
        for key in selector:
            if key.startswith("eks.amazonaws.com/nodegroup"):
                add("WARNING", f"nodeSelector {key} pins pods to a managed node group; select on NodePool labels instead")
    return out


def lint_paths(paths: list[Path]) -> list[Finding]:
    findings: list[Finding] = []
    for path in paths:
        files = sorted(path.rglob("*.y*ml")) if path.is_dir() else [path]
        for f in files:
            try:
                for doc in _documents(f):
                    findings.extend(lint_document(doc, str(f)))
            except yaml.YAMLError as exc:
                findings.append(Finding("ERROR", str(f), "-", f"invalid YAML: {exc}"))
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("paths", nargs="+", type=Path)
    args = parser.parse_args(argv)
    missing = [p for p in args.paths if not p.exists()]
    if missing:
        parser.error(f"not found: {', '.join(map(str, missing))}")
    findings = lint_paths(args.paths)
    for f in findings:
        print(f)
    errors = sum(f.level == "ERROR" for f in findings)
    print(f"{errors} error(s), {len(findings) - errors} warning(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
