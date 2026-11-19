"""Plan and apply a move from IRSA to EKS Pod Identity.

1. scan()      reads Kubernetes manifests, finds service accounts annotated for
               IRSA (eks.amazonaws.com/role-arn) and the workloads that use them,
               and flags workloads Pod Identity cannot serve as they stand.
2. trust()     adds the pods.eks.amazonaws.com statement to an IAM role's trust
               policy and keeps the IRSA statements, so both paths work during
               the migration.
3. plan() / apply()  turn the service accounts into CreatePodIdentityAssociation
               requests, optionally with a cross-account target role or a session
               policy, and create them idempotently.

Do not assume which credentials a pod uses while both IRSA and Pod Identity are
configured for its service account. After creating the association, restart the
pods, check that AWS_CONTAINER_CREDENTIALS_FULL_URI is set, confirm the identity
with `aws sts get-caller-identity`, and then remove the eks.amazonaws.com/role-arn
annotation and the OIDC statement from the role's trust policy.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

IRSA_ANNOTATION = "eks.amazonaws.com/role-arn"
POD_IDENTITY_STATEMENT = {
    "Sid": "EksPodIdentity",
    "Effect": "Allow",
    "Principal": {"Service": "pods.eks.amazonaws.com"},
    "Action": ["sts:AssumeRole", "sts:TagSession"],
}
AGENT_ADDRESSES = ("169.254.170.23", "fd00:ec2::23")
MIN_SDK = {"boto3": (1, 34, 41), "botocore": (1, 34, 41)}
SESSION_POLICY_LIMIT = 2048
WORKLOAD_KINDS = {"Deployment", "StatefulSet", "DaemonSet", "Job", "CronJob", "Pod"}


@dataclass
class ServiceAccount:
    namespace: str
    name: str
    role_arn: str
    workloads: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _docs(paths: list[Path]):
    for path in paths:
        files = sorted(path.rglob("*.y*ml")) if path.is_dir() else [path]
        for f in files:
            for doc in yaml.safe_load_all(f.read_text(encoding="utf-8")):
                if isinstance(doc, dict) and doc.get("kind"):
                    yield doc


def _pod_spec(doc: dict[str, Any]) -> dict[str, Any]:
    spec = doc.get("spec") or {}
    if doc["kind"] == "Pod":
        return spec
    if doc["kind"] == "CronJob":
        spec = (spec.get("jobTemplate") or {}).get("spec") or {}
    return ((spec.get("template") or {}).get("spec")) or {}


def scan(paths: list[Path]) -> list[ServiceAccount]:
    docs = list(_docs(paths))
    accounts: dict[tuple[str, str], ServiceAccount] = {}
    for d in docs:
        meta = d.get("metadata") or {}
        role = (meta.get("annotations") or {}).get(IRSA_ANNOTATION)
        if d["kind"] == "ServiceAccount" and role:
            key = (meta.get("namespace", "default"), meta["name"])
            accounts[key] = ServiceAccount(key[0], key[1], role)

    for d in docs:
        if d["kind"] not in WORKLOAD_KINDS:
            continue
        meta = d.get("metadata") or {}
        pod = _pod_spec(d)
        sa = accounts.get((meta.get("namespace", "default"), pod.get("serviceAccountName", "default")))
        if not sa:
            continue
        sa.workloads.append(f"{d['kind']}/{meta.get('name')}")
        selector = pod.get("nodeSelector") or {}
        if selector.get("kubernetes.io/os") == "windows":
            sa.blockers.append(f"{d['kind']}/{meta.get('name')}: Windows nodes are not supported by Pod Identity")
        if pod.get("hostNetwork"):
            sa.warnings.append(f"{d['kind']}/{meta.get('name')}: hostNetwork pods can also reach the node's instance metadata")
        for c in pod.get("containers", []) + pod.get("initContainers", []):
            env = {e.get("name", "").upper(): str(e.get("value", "")) for e in c.get("env", []) or []}
            if (env.get("HTTPS_PROXY") or env.get("HTTP_PROXY")) and not all(
                    a in env.get("NO_PROXY", "") for a in AGENT_ADDRESSES):
                sa.blockers.append(f"{d['kind']}/{meta.get('name')}/{c.get('name')}: proxy set; add "
                                   "169.254.170.23 and fd00:ec2::23 to NO_PROXY")
    for sa in accounts.values():
        sa.warnings.append("check the namespace is not served by a Fargate profile; Fargate is not supported")
    return sorted(accounts.values(), key=lambda s: (s.namespace, s.name))


def check_sdk(requirements: str) -> list[str]:
    """Flag pinned Python SDK versions too old for the Pod Identity credential provider."""
    problems = []
    for line in requirements.splitlines():
        m = re.match(r"\s*(boto3|botocore)\s*==\s*(\d+)\.(\d+)\.(\d+)", line)
        if m and tuple(map(int, m.groups()[1:])) < MIN_SDK[m.group(1)]:
            need = ".".join(map(str, MIN_SDK[m.group(1)]))
            problems.append(f"{line.strip()}: Pod Identity needs {m.group(1)}>={need}")
    return problems


def trust(policy: dict[str, Any]) -> dict[str, Any]:
    """Return the trust policy with the Pod Identity statement added once."""
    new = copy.deepcopy(policy)
    statements = new.setdefault("Statement", [])
    if isinstance(statements, dict):
        statements = new["Statement"] = [statements]
    if not any(s.get("Principal", {}).get("Service") == "pods.eks.amazonaws.com" for s in statements):
        statements.append(copy.deepcopy(POD_IDENTITY_STATEMENT))
    return new


def plan(cluster: str, accounts: list[ServiceAccount], *, target_roles: dict[str, str] | None = None,
         session_policies: dict[str, dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """CreatePodIdentityAssociation arguments, keyed by namespace/name in the optional maps."""
    target_roles, session_policies = target_roles or {}, session_policies or {}
    requests = []
    for sa in accounts:
        if sa.blockers:
            continue
        key = f"{sa.namespace}/{sa.name}"
        req: dict[str, Any] = {"clusterName": cluster, "namespace": sa.namespace,
                               "serviceAccount": sa.name, "roleArn": sa.role_arn}
        if key in target_roles:
            req["targetRoleArn"] = target_roles[key]
        if key in session_policies:
            text = json.dumps(session_policies[key], separators=(",", ":"))
            if len(text) > SESSION_POLICY_LIMIT:
                raise ValueError(f"{key}: session policy is {len(text)} characters; the limit is {SESSION_POLICY_LIMIT}")
            req["policy"] = text
            req["disableSessionTags"] = True     # session policies and session tags cannot be combined
        requests.append(req)
    return requests


def apply(client: Any, requests: list[dict[str, Any]]) -> list[str]:
    """Create associations; an existing association for the same service account is left alone."""
    results = []
    for req in requests:
        try:
            arn = client.create_pod_identity_association(**req)["association"]["associationArn"]
            results.append(f"created {req['namespace']}/{req['serviceAccount']}: {arn}")
        except client.exceptions.ResourceInUseException:
            results.append(f"exists  {req['namespace']}/{req['serviceAccount']}")
    return results


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Plan an IRSA to EKS Pod Identity migration")
    ap.add_argument("cluster")
    ap.add_argument("paths", nargs="+", type=Path)
    args = ap.parse_args(argv)
    accounts = scan(args.paths)
    for sa in accounts:
        state = "BLOCKED" if sa.blockers else "READY"
        print(f"{state:<8}{sa.namespace}/{sa.name} -> {sa.role_arn} ({', '.join(sa.workloads) or 'no workloads'})")
        for b in sa.blockers:
            print(f"  blocker: {b}")
        for w in sa.warnings:
            print(f"  check:   {w}")
    print(json.dumps(plan(args.cluster, accounts), indent=2))
    return 1 if any(sa.blockers for sa in accounts) else 0


if __name__ == "__main__":
    sys.exit(main())
