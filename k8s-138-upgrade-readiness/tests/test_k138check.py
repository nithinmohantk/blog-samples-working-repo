from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from k138check.checks import (
    check_env_vars,
    check_kubelet_config,
    check_kuberc,
    check_pod_level_swap,
    check_webhooks,
)
from k138check.findings import Severity
from k138check.quantity import QuantityError, parse_quantity
from k138check.scanner import main, scan

ROOT = Path(__file__).resolve().parent.parent
BEFORE = ROOT / "fixtures" / "before"
AFTER = ROOT / "fixtures" / "after"


def pod(pod_resources: dict | None, containers: list[dict]) -> dict:
    spec: dict = {"containers": containers}
    if pod_resources is not None:
        spec["resources"] = pod_resources
    return {"apiVersion": "v1", "kind": "Pod", "metadata": {"name": "p", "namespace": "ns"}, "spec": spec}


def container(name: str, request: str | None = None, limit: str | None = None) -> dict:
    resources: dict = {}
    if request is not None:
        resources["requests"] = {"memory": request}
    if limit is not None:
        resources["limits"] = {"memory": limit}
    return {"name": name, "image": "example", "resources": resources}


# Quantities


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1Gi", Decimal(2**30)),
        ("0.5Gi", Decimal(2**29)),
        ("512Mi", Decimal(2**29)),
        ("1G", Decimal(10**9)),
        ("128974848", Decimal(128974848)),
        ("129e6", Decimal(129_000_000)),
        ("100m", Decimal("0.1")),
        (1024, Decimal(1024)),
    ],
)
def test_parse_quantity(text, expected):
    assert parse_quantity(text) == expected


@pytest.mark.parametrize("bad", ["", "1 Gi", "Gi", "1gi", "1KB", None, True, "abc"])
def test_parse_quantity_rejects(bad):
    with pytest.raises(QuantityError):
        parse_quantity(bad)


# kubectl environment variables


def test_env_vars_reports_each_line():
    text = (BEFORE / "ci-debug.sh").read_text()
    findings = check_env_vars("ci-debug.sh", text)
    assert [f.subject for f in findings] == ["line 5", "line 6"]
    assert all(f.check == "K138-ENV" and f.severity is Severity.WARN for f in findings)


def test_env_vars_clean():
    assert check_env_vars("ci-debug.sh", (AFTER / "ci-debug.sh").read_text()) == []


# kuberc


def test_kuberc_name_alias_needs_action():
    doc = yaml.safe_load((BEFORE / "kuberc").read_text())
    findings = check_kuberc("kuberc", doc)
    by_severity = {f.severity: f for f in findings}
    assert by_severity[Severity.ACTION].subject == "credentialPluginAllowlist[0]"
    assert by_severity[Severity.INFO].subject == "apiVersion"
    assert len(findings) == 2


def test_kuberc_v1_with_command_is_clean():
    assert check_kuberc("kuberc", yaml.safe_load((AFTER / "kuberc").read_text())) == []


def test_kuberc_ignores_other_preference_kinds():
    assert check_kuberc("x.yaml", {"apiVersion": "example.com/v1", "kind": "Preference"}) == []


def test_kuberc_alias_name_is_not_flagged():
    doc = {
        "apiVersion": "kubectl.config.k8s.io/v1",
        "kind": "Preference",
        "aliases": [{"name": "getn", "command": "get"}],
    }
    assert check_kuberc("kuberc", doc) == []


# kubelet configuration


def test_kubelet_config_flags_driver_and_cgroup_v1():
    doc = yaml.safe_load((BEFORE / "kubelet-config.yaml").read_text())
    findings = {f.check: f for f in check_kubelet_config("kubelet-config.yaml", doc)}
    assert findings["K138-CGROUPDRIVER"].severity is Severity.ACTION
    assert findings["K138-CGROUPV1"].severity is Severity.WARN


def test_kubelet_config_clean():
    doc = yaml.safe_load((AFTER / "kubelet-config.yaml").read_text())
    assert check_kubelet_config("kubelet-config.yaml", doc) == []


def test_kubelet_config_fail_cgroup_v1_true_is_fine():
    doc = {"kind": "KubeletConfiguration", "failCgroupV1": True}
    assert check_kubelet_config("k.yaml", doc) == []


# admission webhooks


def test_webhooks_named_and_wildcard():
    docs = list(yaml.safe_load_all((BEFORE / "webhooks.yaml").read_text()))
    named = check_webhooks("webhooks.yaml", docs[0])
    wildcard = check_webhooks("webhooks.yaml", docs[1])
    assert len(named) == 1 and named[0].severity is Severity.ACTION
    for resource in (
        "authentication.k8s.io/tokenreviews",
        "authorization.k8s.io/selfsubjectaccessreviews",
        "authorization.k8s.io/subjectaccessreviews",
    ):
        assert resource in named[0].message
    assert len(wildcard) == 1 and wildcard[0].severity is Severity.INFO


def test_webhooks_same_resource_name_in_other_group_is_ignored():
    doc = {
        "kind": "ValidatingWebhookConfiguration",
        "metadata": {"name": "x"},
        "webhooks": [
            {"name": "w", "rules": [{"apiGroups": ["example.com"], "resources": ["tokenreviews"]}]}
        ],
    }
    assert check_webhooks("w.yaml", doc) == []


def test_webhooks_subresource_and_case():
    doc = {
        "kind": "MutatingWebhookConfiguration",
        "metadata": {"name": "x"},
        "webhooks": [
            {
                "name": "w",
                "rules": [{"apiGroups": ["authorization.k8s.io"], "resources": ["LocalSubjectAccessReviews/status"]}],
            }
        ],
    }
    findings = check_webhooks("w.yaml", doc)
    assert len(findings) == 1 and "localsubjectaccessreviews" in findings[0].message


def test_webhooks_clean():
    doc = yaml.safe_load((AFTER / "webhooks.yaml").read_text())
    assert check_webhooks("webhooks.yaml", doc) == []


# pod-level resources and swap


def test_swap_deployment_fixture():
    doc = yaml.safe_load((BEFORE / "report-worker.yaml").read_text())
    findings = check_pod_level_swap("report-worker.yaml", doc)
    assert len(findings) == 1
    assert findings[0].subject == "Deployment/reporting/report-worker"
    assert "worker" in findings[0].message and "log-shipper" not in findings[0].message


def test_swap_fixed_fixture_is_clean():
    doc = yaml.safe_load((AFTER / "report-worker.yaml").read_text())
    assert check_pod_level_swap("report-worker.yaml", doc) == []


def test_swap_equal_values_in_different_units():
    doc = pod({"requests": {"memory": "0.5Gi"}, "limits": {"memory": "512Mi"}}, [container("a", "100Mi", "200Mi")])
    assert len(check_pod_level_swap("p.yaml", doc)) == 1


def test_swap_limit_only_defaults_request_when_no_container_requests():
    doc = pod({"limits": {"memory": "1Gi"}}, [container("a")])
    assert check_pod_level_swap("p.yaml", doc) == []  # nothing can burst, so nothing to report


def test_swap_limit_only_with_container_requests_is_not_modelled():
    doc = pod({"limits": {"memory": "1Gi"}}, [container("a", "100Mi", "200Mi")])
    assert check_pod_level_swap("p.yaml", doc) == []


def test_swap_request_without_container_limit_counts_as_burstable():
    doc = pod({"requests": {"memory": "1Gi"}, "limits": {"memory": "1Gi"}}, [container("a", "100Mi")])
    assert len(check_pod_level_swap("p.yaml", doc)) == 1


def test_swap_no_pod_level_resources():
    assert check_pod_level_swap("p.yaml", pod(None, [container("a", "100Mi", "200Mi")])) == []


def test_swap_cronjob_and_init_container():
    doc = {
        "kind": "CronJob",
        "metadata": {"name": "nightly"},
        "spec": {
            "jobTemplate": {
                "spec": {
                    "template": {
                        "spec": {
                            "resources": {"requests": {"memory": "1Gi"}, "limits": {"memory": "1Gi"}},
                            "initContainers": [container("warm", "64Mi", "128Mi")],
                            "containers": [container("job", "512Mi", "512Mi")],
                        }
                    }
                }
            }
        },
    }
    findings = check_pod_level_swap("c.yaml", doc)
    assert len(findings) == 1 and "warm" in findings[0].message and "job" not in findings[0].message.split(":")[1]


def test_checks_tolerate_malformed_objects():
    junk = {"kind": "Deployment", "spec": "oops", "metadata": []}
    assert check_pod_level_swap("j.yaml", junk) == []
    assert check_webhooks("j.yaml", {"kind": "ValidatingWebhookConfiguration", "webhooks": "x"}) == []
    assert check_kuberc("j", {"apiVersion": "kubectl.config.k8s.io/v1", "kind": "Preference", "credentialPluginAllowlist": "x"}) == []


# scanner and CLI


def test_scan_before_tree():
    result = scan([BEFORE])
    checks = sorted(f.check for f in result.findings)
    assert checks == [
        "K138-CGROUPDRIVER",
        "K138-CGROUPV1",
        "K138-ENV",
        "K138-ENV",
        "K138-KUBERC",
        "K138-KUBERC",
        "K138-SWAP",
        "K138-WEBHOOK",
        "K138-WEBHOOK",
    ]
    assert result.files_scanned == 5 and result.skipped == []
    assert result.findings[0].severity is Severity.ACTION  # sorted worst first


def test_scan_after_tree_is_clean():
    result = scan([AFTER])
    assert result.findings == [] and result.files_scanned == 5


def test_scan_reports_unparseable_yaml_and_opens_lists(tmp_path):
    (tmp_path / "chart.yaml").write_text("metadata:\n  name: {{ .Release.Name }}\n  labels: {{- include \"x\" . | nindent 4 }}\n")
    listing = {"apiVersion": "v1", "kind": "List", "items": [yaml.safe_load((BEFORE / "kubelet-config.yaml").read_text())]}
    (tmp_path / "dump.json").write_text(json.dumps(listing))
    (tmp_path / "blob.bin").write_bytes(b"\x00\x01KUBECTL_REMOTE_COMMAND_WEBSOCKETS")
    result = scan([tmp_path])
    assert [p for p, _ in result.skipped] == [(tmp_path / "chart.yaml").as_posix()]
    assert {f.check for f in result.findings} == {"K138-CGROUPDRIVER", "K138-CGROUPV1"}


def test_cli_exit_codes_and_json(capsys, tmp_path):
    assert main([str(BEFORE)]) == 1
    capsys.readouterr()
    assert main([str(AFTER)]) == 0
    assert "0 action, 0 warn, 0 info" in capsys.readouterr().out
    assert main([str(BEFORE), "--format", "json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["filesScanned"] == 5 and len(payload["findings"]) == 9
    assert payload["findings"][0]["severity"] == "ACTION"
    assert main([str(tmp_path / "missing")]) == 2
    with pytest.raises(SystemExit) as excinfo:
        main([str(AFTER), "--fail-on", "panic"])
    assert excinfo.value.code == 2


def test_cli_fail_on_threshold(tmp_path, capsys):
    target = tmp_path / "ci.sh"
    target.write_text((BEFORE / "ci-debug.sh").read_text())
    assert main([str(target)]) == 0  # warnings only, default threshold is action
    assert main([str(target), "--fail-on", "warn"]) == 1
    capsys.readouterr()
