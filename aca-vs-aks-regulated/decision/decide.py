"""Recommend a container platform for a regulated workload from a short list of facts about it.

    python decide.py requirements.json

The rules are deliberately few and written down, so the recommendation can be argued with. Hard
requirements (things one platform cannot do) decide first; only then do team and cost factors apply.
Prints the recommendation and every reason. Exit code 0.
"""
from __future__ import annotations

import json
import pathlib
import sys

# A true answer to any of these needs the Kubernetes API or node-level access, which Container Apps does not expose.
NEEDS_KUBERNETES = {
    "needs_kubernetes_api": "The workload or its tooling uses the Kubernetes API (operators, custom resources, Helm charts that create them).",
    "needs_network_policy_between_services": "Traffic between services on the same platform must be restricted by policy.",
    "needs_daemonsets_or_privileged": "Something has to run on every node or with elevated privileges (agents, eBPF tools, device plugins).",
    "needs_custom_service_mesh": "A specific service mesh or sidecar set is mandated.",
    "needs_windows_containers": "Some containers are Windows containers.",
}
# A true answer to any of these needs choices AKS Automatic makes for you.
NEEDS_STANDARD = {
    "needs_custom_node_configuration": "Node pools need specific images, kernel settings, taints or sizes chosen by you.",
    "needs_own_upgrade_schedule_per_pool": "Upgrades must be staged by you, pool by pool, on your own schedule.",
    "needs_bring_your_own_cni": "A CNI other than the built-in options is required.",
}


def decide(facts: dict) -> dict:
    unknown = set(facts) - set(NEEDS_KUBERNETES) - set(NEEDS_STANDARD) - {"team_operates_kubernetes_today", "workload"}
    if unknown:
        raise ValueError(f"unknown facts: {', '.join(sorted(unknown))}")
    kubernetes = [text for key, text in NEEDS_KUBERNETES.items() if facts.get(key)]
    standard = [text for key, text in NEEDS_STANDARD.items() if facts.get(key)]
    operates = bool(facts.get("team_operates_kubernetes_today"))
    cautions: list[str] = []

    if not kubernetes and not standard:
        platform = "Azure Container Apps"
        reasons = ["Nothing in the requirements needs the Kubernetes API or node access.",
                   "Microsoft patches the nodes, the Kubernetes layer and the ingress; your duties shrink to the image, identity, egress and evidence."]
        if operates:
            cautions.append("The team already runs Kubernetes. That is a reason AKS would be affordable, not a requirement for it.")
    elif not standard:
        platform = "AKS Automatic"
        reasons = kubernetes + ["Nothing requires control over node configuration or upgrade staging, so let the platform manage nodes and upgrades."]
        if not operates:
            cautions.append("The team does not run Kubernetes today. Budget for the skills: you own RBAC, network policy and manifests on day one.")
    else:
        platform = "AKS Standard"
        reasons = kubernetes + standard
        if not operates:
            cautions.append("The team does not run Kubernetes today, and AKS Standard leaves upgrades and node patching with you. Staff it before you choose it.")
        if not kubernetes:
            cautions.append("Only node-level control points to AKS. Check whether a dedicated workload profile on Container Apps would meet the underlying need.")
    return {"platform": platform, "reasons": reasons, "cautions": cautions}


def ownership_counts(path: pathlib.Path) -> dict[str, dict[str, int]]:
    duties = json.loads(path.read_text(encoding="utf-8"))["duties"]
    counts: dict[str, dict[str, int]] = {}
    for platform in ("aca", "aks_automatic", "aks_standard"):
        counts[platform] = {}
        for duty in duties:
            counts[platform][duty[platform]] = counts[platform].get(duty[platform], 0) + 1
    return counts


def main() -> int:
    facts = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
    result = decide(facts)
    print(f"Recommendation: {result['platform']}")
    for reason in result["reasons"]:
        print(f"  because  {reason}")
    for caution in result["cautions"]:
        print(f"  caution  {caution}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
