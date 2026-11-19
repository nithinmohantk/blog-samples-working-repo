import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import automode_lint as al  # noqa: E402

LEGACY = """
apiVersion: karpenter.k8s.aws/v1
kind: EC2NodeClass
metadata: {name: default}
spec:
  amiFamily: AL2023
  role: KarpenterNodeRole
  subnetSelectorTerms: [{tags: {karpenter.sh/discovery: orders}}]
  securityGroupSelectorTerms: [{tags: {karpenter.sh/discovery: orders}}]
---
apiVersion: karpenter.sh/v1
kind: NodePool
metadata: {name: general}
spec:
  template:
    spec:
      nodeClassRef: {group: karpenter.k8s.aws, kind: EC2NodeClass, name: default}
      expireAfter: 720h
      requirements:
        - {key: karpenter.k8s.aws/instance-category, operator: In, values: [c, m]}
        - {key: karpenter.k8s.aws/instance-tenancy, operator: In, values: [default]}
        - {key: kubernetes.io/os, operator: In, values: [windows]}
---
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata: {name: gp3}
provisioner: ebs.csi.aws.com
---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: web
  annotations:
    kubernetes.io/ingress.class: alb
    alb.ingress.kubernetes.io/group.name: shared
spec: {}
---
apiVersion: apps/v1
kind: Deployment
metadata: {name: api}
spec:
  template:
    spec:
      nodeSelector: {eks.amazonaws.com/nodegroup: ng-1}
      containers: [{name: api, image: api:1}]
"""


def messages(findings):
    return [(f.level, f.obj, f.message) for f in findings]


def test_sample_manifests_are_clean():
    assert al.lint_paths([ROOT / "manifests"]) == []


def test_legacy_manifests_are_flagged(tmp_path):
    (tmp_path / "legacy.yaml").write_text(LEGACY)
    found = messages(al.lint_paths([tmp_path]))
    text = "\n".join(f"{lvl} {obj} {msg}" for lvl, obj, msg in found)
    assert "ERROR EC2NodeClass/default Karpenter EC2NodeClass is not used" in text
    assert "ERROR NodePool/general nodeClassRef must be" in text
    assert "use eks.amazonaws.com/instance-category" in text
    assert "instance-tenancy" not in text
    assert "kubernetes.io/os is not supported" in text
    assert "expireAfter 720h exceeds" in text
    assert "WARNING StorageClass/gp3 provisioner ebs.csi.aws.com" in text
    assert "kubernetes.io/ingress.class is not supported" in text
    assert "group.name is not supported" in text
    assert "WARNING Deployment/api nodeSelector eks.amazonaws.com/nodegroup" in text


def test_auto_mode_nodeclass_unsupported_fields(tmp_path):
    (tmp_path / "nc.yaml").write_text("""
apiVersion: eks.amazonaws.com/v1
kind: NodeClass
metadata: {name: custom}
spec:
  role: R
  instanceProfile: P
  userData: "#!/bin/bash"
  blockDeviceMappings: []
  subnetSelectorTerms: [{id: subnet-1}]
""")
    found = [m for _, _, m in messages(al.lint_paths([tmp_path]))]
    assert any("spec.userData is not supported" in m for m in found)
    assert any("spec.blockDeviceMappings is not supported" in m and "ephemeralStorage" in m for m in found)
    assert any("mutually exclusive" in m for m in found)
    assert any("securityGroupSelectorTerms is required" in m for m in found)


@pytest.mark.parametrize("value,hours", [("336h", 336), ("504h", 504), ("90m", 1.5), ("1h30m", 1.5),
                                         ("Never", float("inf")), ("two weeks", None), ("", None)])
def test_parse_hours(value, hours):
    assert al.parse_hours(value) == hours


def test_expire_never_is_rejected(tmp_path):
    (tmp_path / "np.yaml").write_text("""
apiVersion: karpenter.sh/v1
kind: NodePool
metadata: {name: p}
spec:
  template:
    spec:
      nodeClassRef: {group: eks.amazonaws.com, kind: NodeClass, name: default}
      expireAfter: Never
""")
    assert any("exceeds" in f.message for f in al.lint_paths([tmp_path]))


def test_cli_exit_codes(tmp_path, capsys):
    assert al.main([str(ROOT / "manifests")]) == 0
    (tmp_path / "legacy.yaml").write_text(LEGACY)
    assert al.main([str(tmp_path)]) == 1
    assert "error(s)" in capsys.readouterr().out
