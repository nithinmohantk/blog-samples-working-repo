"""Offline tests. botocore's Stubber validates every request and response
against the SageMaker service model shipped with the pinned boto3, so a
misspelled operation or parameter fails the test."""

import boto3
import pytest
from botocore.exceptions import ParamValidationError
from botocore.stub import Stubber

import readiness

DOMAIN = "d-abc123def456"


def _client():
    return boto3.client("sagemaker", region_name="eu-west-1",
                        aws_access_key_id="x", aws_secret_access_key="x")


def _stub_domain(stub, *, network="VpcOnly", landing="studio::", classic=True):
    stub.add_response("describe_domain", {
        "DomainId": DOMAIN, "DomainName": "ml-platform", "AuthMode": "IAM",
        "AppNetworkAccessType": network,
        "DefaultUserSettings": {
            "ExecutionRole": "arn:aws:iam::111122223333:role/sm-exec",
            "DefaultLandingUri": landing,
            "StudioWebPortal": "ENABLED",
            "JupyterLabAppSettings": {
                "CustomImages": [{"ImageName": "geo", "AppImageConfigName": "geo-cfg"}],
                "LifecycleConfigArns": ["arn:aws:sagemaker:eu-west-1:111122223333:studio-lifecycle-config/pip"],
            },
        },
        "DomainSettings": {},
    }, {"DomainId": DOMAIN})
    apps = [{"DomainId": DOMAIN, "AppType": "JupyterLab", "AppName": "default", "Status": "InService", "SpaceName": "alice"},
            {"DomainId": DOMAIN, "AppType": "Canvas", "AppName": "default", "Status": "InService", "UserProfileName": "bob"},
            {"DomainId": DOMAIN, "AppType": "JupyterLab", "AppName": "old", "Status": "Deleted", "SpaceName": "carol"}]
    if classic:
        apps.append({"DomainId": DOMAIN, "AppType": "KernelGateway", "AppName": "k1", "Status": "InService", "UserProfileName": "bob"})
    # Two pages, to prove pagination is followed.
    stub.add_response("list_apps", {"Apps": apps[:2], "NextToken": "t1"}, {"DomainIdEquals": DOMAIN})
    stub.add_response("list_apps", {"Apps": apps[2:]}, {"DomainIdEquals": DOMAIN, "NextToken": "t1"})
    stub.add_response("list_user_profiles", {"UserProfiles": [
        {"DomainId": DOMAIN, "UserProfileName": "alice"}, {"DomainId": DOMAIN, "UserProfileName": "bob"}]},
        {"DomainIdEquals": DOMAIN})
    stub.add_response("list_spaces", {"Spaces": [{"DomainId": DOMAIN, "SpaceName": "alice"}]},
                      {"DomainIdEquals": DOMAIN})


def test_collect_and_assess_flags_classic_vpc_images_canvas():
    client = _client()
    with Stubber(client) as stub:
        _stub_domain(stub)
        inv = readiness.collect(client, DOMAIN)
        stub.assert_no_pending_responses()

    assert inv.apps_by_type == {"JupyterLab": 1, "Canvas": 1, "KernelGateway": 1}  # Deleted ignored
    assert inv.user_profiles == ["alice", "bob"] and inv.spaces == ["alice"]
    areas = {f.area: f.severity for f in readiness.assess(inv)}
    assert areas["studio-classic"] == "blocker"
    assert areas["network"] == areas["images"] == areas["lifecycle"] == areas["canvas"] == "review"


def test_clean_domain_has_no_blocker():
    client = _client()
    with Stubber(client) as stub:
        _stub_domain(stub, network="PublicInternetOnly", classic=False)
        inv = readiness.collect(client, DOMAIN)
    findings = readiness.assess(inv)
    assert not [f for f in findings if f.severity == "blocker"]
    assert "network" not in {f.area for f in findings}


def test_classic_landing_uri_alone_is_a_blocker():
    client = _client()
    with Stubber(client) as stub:
        _stub_domain(stub, landing="app:JupyterServer:", classic=False)
        inv = readiness.collect(client, DOMAIN)
    assert any(f.area == "studio-classic" for f in readiness.assess(inv))


def test_main_returns_2_on_access_denied(monkeypatch, capsys):
    client = _client()
    stub = Stubber(client)
    stub.add_client_error("describe_domain", "AccessDeniedException", "not allowed", 400,
                          expected_params={"DomainId": DOMAIN})
    stub.activate()
    monkeypatch.setattr(readiness, "make_client", lambda region: client)
    assert readiness.main(["--domain-id", DOMAIN, "--region", "eu-west-1"]) == 2


def test_update_domain_request_shape_is_valid():
    """The request an administrator would send to link a domain to a Unified
    Studio project. Stubber rejects it if any field name is wrong."""
    client = _client()
    params = {"DomainId": DOMAIN, "DomainSettingsForUpdate": {"UnifiedStudioSettings": {
        "StudioWebPortalAccess": "ENABLED", "DomainId": "dzd_abc123", "ProjectId": "p123abc",
        "EnvironmentId": "env123", "DomainRegion": "eu-west-1", "DomainAccountId": "111122223333",
        "ProjectS3Path": "s3://amzn-sagemaker-111122223333/dzd_abc123/p123abc/"}}}
    with Stubber(client) as stub:
        stub.add_response("update_domain", {"DomainArn": f"arn:aws:sagemaker:eu-west-1:111122223333:domain/{DOMAIN}"}, params)
        client.update_domain(**params)
    with pytest.raises(ParamValidationError):
        client.update_domain(DomainId=DOMAIN, DomainSettingsForUpdate={"UnifiedStudio": {}})
