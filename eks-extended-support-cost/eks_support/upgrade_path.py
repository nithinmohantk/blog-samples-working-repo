"""Upgrade steps to a target version, one minor version at a time.

EKS upgrades the control plane one minor version per update. Each step lists
the API versions that Kubernetes stopped serving in that release (Kubernetes
Deprecated API Migration Guide) and EKS-specific changes worth checking.
"""
from __future__ import annotations

REMOVED_IN = {
    "1.24": ["dockershim: EKS 1.24 nodes support containerd only, not the Docker runtime"],
    "1.25": ["policy/v1beta1 PodSecurityPolicy (no replacement API; use Pod Security Admission)",
             "batch/v1beta1 CronJob", "discovery.k8s.io/v1beta1 EndpointSlice", "events.k8s.io/v1beta1 Event",
             "autoscaling/v2beta1 HorizontalPodAutoscaler", "policy/v1beta1 PodDisruptionBudget",
             "node.k8s.io/v1beta1 RuntimeClass"],
    "1.26": ["flowcontrol.apiserver.k8s.io/v1beta1 FlowSchema and PriorityLevelConfiguration",
             "autoscaling/v2beta2 HorizontalPodAutoscaler"],
    "1.27": ["storage.k8s.io/v1beta1 CSIStorageCapacity"],
    "1.28": [],
    "1.29": ["flowcontrol.apiserver.k8s.io/v1beta2 FlowSchema and PriorityLevelConfiguration"],
}


def _minor(version: str) -> int:
    major, minor = version.split(".")
    if major != "1":
        raise ValueError(version)
    return int(minor)


def steps(current: str, target: str) -> list[dict]:
    """[{'to': '1.25', 'removed': [...]}, ...] from current to target."""
    if _minor(target) < _minor(current):
        raise ValueError(f"cannot downgrade {current} to {target}")
    return [{"to": f"1.{m}", "removed": REMOVED_IN.get(f"1.{m}", ["(not listed)"])}
            for m in range(_minor(current) + 1, _minor(target) + 1)]
