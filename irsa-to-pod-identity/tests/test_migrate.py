"""EKS calls go through botocore's Stubber, which validates them against the
EKS API model in the pinned botocore release."""

import json
from datetime import datetime, timezone
from pathlib import Path

import boto3
import pytest
from botocore.stub import Stubber

import migrate as m

EXAMPLES = Path(__file__).parent.parent / "examples"
NOW = datetime(2026, 4, 28, tzinfo=timezone.utc)


def eks():
    return boto3.client("eks", region_name="eu-west-1", aws_access_key_id="x", aws_secret_access_key="x")


def test_scan_finds_irsa_accounts_and_blockers():
    accounts = {f"{a.namespace}/{a.name}": a for a in m.scan([EXAMPLES])}
    assert set(accounts) == {"orders/orders-api", "billing/invoice-export"}
    assert accounts["billing/invoice-export"].workloads == ["CronJob/invoice-export"]
    assert accounts["billing/invoice-export"].blockers == []
    blockers = accounts["orders/orders-api"].blockers
    assert len(blockers) == 1 and "NO_PROXY" in blockers[0]


def test_windows_and_host_network(tmp_path):
    (tmp_path / "w.yaml").write_text("""
apiVersion: v1
kind: ServiceAccount
metadata: {name: win, namespace: ops, annotations: {eks.amazonaws.com/role-arn: arn:aws:iam::111122223333:role/win}}
---
apiVersion: apps/v1
kind: DaemonSet
metadata: {name: agent, namespace: ops}
spec:
  template:
    spec:
      serviceAccountName: win
      hostNetwork: true
      nodeSelector: {kubernetes.io/os: windows}
      containers: [{name: a, image: x}]
""")
    sa = m.scan([tmp_path])[0]
    assert "Windows" in sa.blockers[0]
    assert any("hostNetwork" in w for w in sa.warnings)


def test_trust_policy_keeps_irsa_and_is_idempotent():
    irsa = {"Version": "2012-10-17", "Statement": [{
        "Effect": "Allow",
        "Principal": {"Federated": "arn:aws:iam::111122223333:oidc-provider/oidc.eks.eu-west-1.amazonaws.com/id/EXAMPLE"},
        "Action": "sts:AssumeRoleWithWebIdentity"}]}
    once = m.trust(irsa)
    assert len(once["Statement"]) == 2
    assert once["Statement"][1]["Principal"] == {"Service": "pods.eks.amazonaws.com"}
    assert m.trust(once) == once
    assert len(irsa["Statement"]) == 1  # input not modified


def test_plan_skips_blocked_and_adds_options():
    accounts = m.scan([EXAMPLES])
    policy = {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": "s3:PutObject",
                                                      "Resource": "arn:aws:s3:::invoices-export/*"}]}
    reqs = m.plan("prod-eu", accounts,
                  target_roles={"billing/invoice-export": "arn:aws:iam::444455556666:role/finance-bucket-writer"},
                  session_policies={"billing/invoice-export": policy})
    assert len(reqs) == 1
    r = reqs[0]
    assert r["targetRoleArn"].startswith("arn:aws:iam::444455556666")
    assert r["disableSessionTags"] is True and json.loads(r["policy"]) == policy


def test_session_policy_limit():
    sa = m.ServiceAccount("a", "b", "arn:aws:iam::111122223333:role/r")
    big = {"Statement": [{"Effect": "Allow", "Action": "s3:GetObject", "Resource": "x" * 2100}]}
    with pytest.raises(ValueError, match="limit is 2048"):
        m.plan("c", [sa], session_policies={"a/b": big})


def test_apply_requests_match_model_and_tolerate_existing():
    reqs = m.plan("prod-eu", [m.ServiceAccount("billing", "invoice-export", "arn:aws:iam::111122223333:role/invoice-export"),
                              m.ServiceAccount("orders", "orders-api", "arn:aws:iam::111122223333:role/orders-api")],
                  target_roles={"billing/invoice-export": "arn:aws:iam::444455556666:role/finance-bucket-writer"})
    c = eks()
    with Stubber(c) as stub:
        stub.add_response("create_pod_identity_association", {"association": {
            "clusterName": "prod-eu", "namespace": "billing", "serviceAccount": "invoice-export",
            "roleArn": "arn:aws:iam::111122223333:role/invoice-export",
            "associationArn": "arn:aws:eks:eu-west-1:111122223333:podidentityassociation/prod-eu/a-1",
            "associationId": "a-1", "createdAt": NOW, "modifiedAt": NOW}}, reqs[0])
        stub.add_client_error("create_pod_identity_association", "ResourceInUseException",
                              http_status_code=409, expected_params=reqs[1])
        out = m.apply(c, reqs)
    assert out[0].startswith("created billing/invoice-export") and out[1].startswith("exists  orders/orders-api")


def test_check_sdk():
    assert m.check_sdk("boto3==1.34.40\nbotocore==1.34.41\nrequests==2.32.3") == [
        "boto3==1.34.40: Pod Identity needs boto3>=1.34.41"]


def test_cli_exit_code(capsys):
    assert m.main(["prod-eu", str(EXAMPLES)]) == 1
    out = capsys.readouterr().out
    assert "BLOCKED orders/orders-api" in out and "READY   billing/invoice-export" in out
