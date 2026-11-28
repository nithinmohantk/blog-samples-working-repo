"""The five checks. Each takes parsed input and returns a list of findings.

Checks never raise on malformed manifests: a field of the wrong type is
treated as absent, because the scanner runs over repositories it does not own.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from decimal import Decimal
from typing import Any

from .findings import Finding, Severity
from .quantity import QuantityError, parse_quantity

KEP_4006 = "https://kubernetes.dev/resources/keps/4006"
KEP_3104 = "https://kubernetes.dev/resources/keps/3104"
KEP_4033 = "https://kubernetes.dev/resources/keps/4033"
KEP_5573 = "https://kubernetes.dev/resources/keps/5573"
KEP_5793 = "https://kubernetes.dev/resources/keps/5793"
KEP_2837 = "https://kubernetes.dev/resources/keps/2837"

REMOVED_KUBECTL_ENV_VARS = (
    "KUBECTL_REMOTE_COMMAND_WEBSOCKETS",
    "KUBECTL_PORT_FORWARD_WEBSOCKETS",
)

KUBERC_GROUP = "kubectl.config.k8s.io"

# Virtual review resources that admission webhooks no longer receive.
REVIEW_RESOURCES = {
    "authentication.k8s.io": {"tokenreviews", "selfsubjectreviews"},
    "authorization.k8s.io": {
        "subjectaccessreviews",
        "selfsubjectaccessreviews",
        "localsubjectaccessreviews",
        "selfsubjectrulesreviews",
    },
}

WEBHOOK_KINDS = {"ValidatingWebhookConfiguration", "MutatingWebhookConfiguration"}

# Where the pod spec sits inside each workload kind.
POD_SPEC_PATHS: dict[str, tuple[str, ...]] = {
    "Pod": ("spec",),
    "Deployment": ("spec", "template", "spec"),
    "StatefulSet": ("spec", "template", "spec"),
    "DaemonSet": ("spec", "template", "spec"),
    "ReplicaSet": ("spec", "template", "spec"),
    "Job": ("spec", "template", "spec"),
    "CronJob": ("spec", "jobTemplate", "spec", "template", "spec"),
}


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: Any) -> Sequence[Any]:
    return value if isinstance(value, list) else []


def _dig(doc: Mapping[str, Any], path: Sequence[str]) -> Mapping[str, Any]:
    current: Any = doc
    for key in path:
        current = _mapping(current).get(key)
    return _mapping(current)


def _subject(doc: Mapping[str, Any]) -> str:
    meta = _mapping(doc.get("metadata"))
    name = meta.get("name") or "<unnamed>"
    namespace = meta.get("namespace")
    kind = doc.get("kind") or "<no kind>"
    return f"{kind}/{namespace}/{name}" if namespace else f"{kind}/{name}"


def check_env_vars(path: str, text: str) -> list[Finding]:
    """Removed kubectl opt-out variables anywhere in a text file."""
    findings: list[Finding] = []
    for number, line in enumerate(text.splitlines(), start=1):
        for variable in REMOVED_KUBECTL_ENV_VARS:
            if variable in line:
                findings.append(
                    Finding(
                        check="K138-ENV",
                        severity=Severity.WARN,
                        path=path,
                        subject=f"line {number}",
                        message=(
                            f"{variable} is removed in kubectl v1.38 and is ignored. "
                            "kubectl tries WebSockets first and falls back to SPDY."
                        ),
                        action=(
                            "Delete the variable. If it was set to force SPDY through a proxy "
                            "that blocks WebSocket upgrades, test exec and port-forward through "
                            "that proxy with kubectl v1.38 before rolling it out."
                        ),
                        reference=KEP_4006,
                    )
                )
    return findings


def check_kuberc(path: str, doc: Mapping[str, Any]) -> list[Finding]:
    """kuberc Preference files: the allowlist `name` alias and the beta API version."""
    api_version = str(doc.get("apiVersion", ""))
    if doc.get("kind") != "Preference" or not api_version.startswith(f"{KUBERC_GROUP}/"):
        return []

    findings: list[Finding] = []
    for index, entry in enumerate(_sequence(doc.get("credentialPluginAllowlist"))):
        if "name" in _mapping(entry):
            findings.append(
                Finding(
                    check="K138-KUBERC",
                    severity=Severity.ACTION,
                    path=path,
                    subject=f"credentialPluginAllowlist[{index}]",
                    message=(
                        "Allowlist entry uses `name`. The field was a beta alias for `command`, "
                        f"deprecated since v1.36, and does not exist in {KUBERC_GROUP}/v1."
                    ),
                    action="Rename the key to `command`. Do not set both keys on one entry.",
                    reference=KEP_3104,
                )
            )
    if api_version != f"{KUBERC_GROUP}/v1":
        findings.append(
            Finding(
                check="K138-KUBERC",
                severity=Severity.INFO,
                path=path,
                subject="apiVersion",
                message=f"File declares {api_version}; kubectl v1.38 adds the stable {KUBERC_GROUP}/v1.",
                action=(
                    "Move to v1 once every workstation and CI image runs kubectl v1.38 or later. "
                    "Older clients do not know the v1 version."
                ),
                reference=KEP_3104,
            )
        )
    return findings


def check_kubelet_config(path: str, doc: Mapping[str, Any]) -> list[Finding]:
    """KubeletConfiguration: explicit cgroup driver and the cgroup v1 escape hatch."""
    if doc.get("kind") != "KubeletConfiguration":
        return []

    findings: list[Finding] = []
    driver = doc.get("cgroupDriver")
    if driver:
        findings.append(
            Finding(
                check="K138-CGROUPDRIVER",
                severity=Severity.ACTION,
                path=path,
                subject="cgroupDriver",
                message=(
                    f"cgroupDriver is set to {driver!r}. The v1.38 sneak peek announces that the "
                    "kubelet takes the driver from the container runtime over CRI and rejects "
                    "this field unless the LegacyCgroupDriverFallback feature gate is enabled."
                ),
                action=(
                    "Confirm the node's runtime answers the CRI RuntimeConfig call (containerd 2.0 "
                    "or later, CRI-O 1.28 or later per KEP-4033), make sure the runtime starts "
                    "before the kubelet, then remove the field. Check the final release notes: "
                    "this change was announced before it merged."
                ),
                reference=KEP_4033,
            )
        )
    if doc.get("failCgroupV1") is False:
        findings.append(
            Finding(
                check="K138-CGROUPV1",
                severity=Severity.WARN,
                path=path,
                subject="failCgroupV1",
                message=(
                    "failCgroupV1 is false, so this node configuration is meant for cgroup v1 hosts. "
                    "The setting still works in v1.38; cgroup v1 support is scheduled for removal "
                    "in a later release."
                ),
                action="Plan the move of these nodes to a cgroup v2 operating system image.",
                reference=KEP_5573,
            )
        )
    return findings


def _rule_review_matches(rule: Mapping[str, Any]) -> tuple[set[str], bool]:
    """Return (explicitly named review resources, matched only through wildcards)."""
    groups = {str(g) for g in _sequence(rule.get("apiGroups"))}
    resources = {str(r).split("/", 1)[0].lower() for r in _sequence(rule.get("resources"))}
    named: set[str] = set()
    wildcard = False
    for group, review_resources in REVIEW_RESOURCES.items():
        if group not in groups and "*" not in groups:
            continue
        hits = resources & review_resources
        if hits:
            named |= {f"{group}/{resource}" for resource in hits}
        elif "*" in resources:
            wildcard = True
    return named, wildcard and not named


def check_webhooks(path: str, doc: Mapping[str, Any]) -> list[Finding]:
    """Webhook rules that select authentication or authorization review resources."""
    if doc.get("kind") not in WEBHOOK_KINDS:
        return []

    findings: list[Finding] = []
    subject_prefix = _subject(doc)
    for webhook in _sequence(doc.get("webhooks")):
        webhook_map = _mapping(webhook)
        webhook_name = webhook_map.get("name") or "<unnamed>"
        named_all: set[str] = set()
        wildcard_any = False
        for rule in _sequence(webhook_map.get("rules")):
            named, wildcard = _rule_review_matches(_mapping(rule))
            named_all |= named
            wildcard_any = wildcard_any or wildcard
        if named_all:
            findings.append(
                Finding(
                    check="K138-WEBHOOK",
                    severity=Severity.ACTION,
                    path=path,
                    subject=f"{subject_prefix} webhook {webhook_name}",
                    message=(
                        "Rules name review resources that the API server no longer sends to "
                        "admission webhooks (ExcludeAdmissionWebhookVirtualResources, on by "
                        f"default since v1.37): {', '.join(sorted(named_all))}."
                    ),
                    action=(
                        "Remove these resources from the rules. If a control depends on seeing "
                        "these requests, move it to audit policy or an authorization webhook; "
                        "the feature gate will be locked on when the feature reaches stable."
                    ),
                    reference=KEP_5793,
                )
            )
        elif wildcard_any:
            findings.append(
                Finding(
                    check="K138-WEBHOOK",
                    severity=Severity.INFO,
                    path=path,
                    subject=f"{subject_prefix} webhook {webhook_name}",
                    message=(
                        "A wildcard rule covers the authentication or authorization API groups. "
                        "The webhook is no longer called for review resources in those groups."
                    ),
                    action="No change needed unless the webhook's logic expects review requests.",
                    reference=KEP_5793,
                )
            )
    return findings


def _memory(resources: Mapping[str, Any], section: str) -> Decimal | None:
    raw = _mapping(resources.get(section)).get("memory")
    if raw is None:
        return None
    try:
        return parse_quantity(raw)
    except QuantityError:
        return None


def _containers(pod_spec: Mapping[str, Any]) -> Iterator[Mapping[str, Any]]:
    for key in ("initContainers", "containers"):
        for container in _sequence(pod_spec.get(key)):
            yield _mapping(container)


def check_pod_level_swap(path: str, doc: Mapping[str, Any]) -> list[Finding]:
    """Pods whose pod-level memory request equals the limit while a container can burst.

    On a cgroup v2 node with LimitedSwap, v1.38 sizes swap from the pod-level
    memory settings. Request equal to limit means no swap for the whole pod,
    including containers whose own request is below their limit.
    """
    spec_path = POD_SPEC_PATHS.get(str(doc.get("kind")))
    if spec_path is None:
        return []
    pod_spec = _dig(doc, spec_path)
    pod_resources = _mapping(pod_spec.get("resources"))
    pod_limit = _memory(pod_resources, "limits")
    if pod_limit is None:
        return []

    pod_request = _memory(pod_resources, "requests")
    containers = list(_containers(pod_spec))
    container_requests = [_memory(_mapping(c.get("resources")), "requests") for c in containers]
    if pod_request is None:
        # The API server defaults a missing pod-level request to the pod-level
        # limit only when no container sets a memory request. With container
        # requests present it sums them, which this static check does not model.
        if any(request is not None for request in container_requests):
            return []
        pod_request = pod_limit
    if pod_request != pod_limit:
        return []

    burstable = []
    for container in containers:
        resources = _mapping(container.get("resources"))
        request, limit = _memory(resources, "requests"), _memory(resources, "limits")
        if request is not None and (limit is None or request < limit):
            burstable.append(str(container.get("name") or "<unnamed>"))
    if not burstable:
        return []

    return [
        Finding(
            check="K138-SWAP",
            severity=Severity.WARN,
            path=path,
            subject=_subject(doc),
            message=(
                "Pod-level memory request equals the pod-level limit, and these containers set a "
                f"memory request below their limit: {', '.join(burstable)}. On LimitedSwap nodes "
                "v1.38 gives this pod no swap, including those containers."
            ),
            action=(
                "If the workload relies on swap, set the pod-level memory request below the "
                "pod-level limit and retest on a v1.38 node. If it does not, no change is needed."
            ),
            reference=KEP_2837,
        )
    ]


DOCUMENT_CHECKS = (check_kuberc, check_kubelet_config, check_webhooks, check_pod_level_swap)
