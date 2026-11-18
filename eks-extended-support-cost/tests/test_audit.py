from datetime import date

import boto3
from botocore.stub import Stubber
from moto import mock_aws

from eks_support.audit import audit_region, upgrade_insights

TODAY = date(2024, 2, 24)
ROLE = "arn:aws:iam::123456789012:role/eks-cluster"


def test_audit_reports_status_steps_and_cost_from_moto():
    with mock_aws():
        eks = boto3.client("eks", region_name="eu-west-1")
        for name, version in (("payments-prod", "1.24"), ("data-prod", "1.25"), ("new-svc", "1.29")):
            eks.create_cluster(name=name, version=version, roleArn=ROLE, resourcesVpcConfig={"subnetIds": ["subnet-1"]})
        reports = {r.name: r for r in audit_region(eks, "eu-west-1", TODAY)}
    assert (reports["payments-prod"].status, reports["payments-prod"].steps_to_latest) == ("extended", 5)
    assert reports["payments-prod"].next_12_months["2024-04"] == "432.00"
    assert (reports["data-prod"].status, reports["data-prod"].extended_from) == ("standard", "2024-05-01")
    assert reports["new-svc"].total_12_months == "878.40"  # Feb 2024 to Jan 2025 is 8,784 hours: 2024 is a leap year
    # moto 5.0.2 does not implement ListInsights; the audit records that instead of failing
    assert reports["new-svc"].insights[0]["name"] == "insights unavailable"


def test_upgrade_insights_keeps_only_checks_that_are_not_passing():
    eks = boto3.client("eks", region_name="eu-west-1", aws_access_key_id="x", aws_secret_access_key="x")
    with Stubber(eks) as stub:
        stub.add_response("list_insights", {"insights": [
            {"id": "a", "name": "Deprecated APIs removed in Kubernetes v1.25", "category": "UPGRADE_READINESS",
             "kubernetesVersion": "1.25", "insightStatus": {"status": "ERROR", "reason": "Deprecated API usage detected"}},
            {"id": "b", "name": "Kubelet version skew", "category": "UPGRADE_READINESS",
             "kubernetesVersion": "1.25", "insightStatus": {"status": "PASSING", "reason": "No issues"}},
        ]}, {"clusterName": "payments-prod", "filter": {"categories": ["UPGRADE_READINESS"]}})
        found = upgrade_insights(eks, "payments-prod")
    assert found == [{"name": "Deprecated APIs removed in Kubernetes v1.25", "kubernetesVersion": "1.25", "status": "ERROR"}]
