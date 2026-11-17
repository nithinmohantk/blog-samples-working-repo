"""Runs the finder against moto's in-memory Lambda, so no AWS account is needed."""
import io
import sys
import zipfile
from pathlib import Path

import boto3
import pytest
from moto import mock_iam, mock_lambda

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import find_go1x  # noqa: E402

REGION = "eu-west-1"


def _zip() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("main", b"placeholder")
    return buffer.getvalue()


@pytest.fixture
def account(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", REGION)
    with mock_iam(), mock_lambda():
        role = boto3.client("iam").create_role(
            RoleName="fn", AssumeRolePolicyDocument='{"Version":"2012-10-17","Statement":[]}')["Role"]["Arn"]
        client = boto3.client("lambda", region_name=REGION)

        def create(name, runtime, handler, publish=False):
            return client.create_function(FunctionName=name, Runtime=runtime, Role=role, Handler=handler,
                                          Code={"ZipFile": _zip()}, Publish=publish)

        old = create("orders-go", "go1.x", "main", publish=True)
        client.create_alias(FunctionName="orders-go", Name="live", FunctionVersion=old["Version"])
        create("already-moved", "provided.al2023", "bootstrap")
        create("python-fn", "python3.12", "app.handler")
        create("legacy-java", "java8", "example.Handler::handleRequest")
        yield client


def test_finds_go1x_latest_and_published_versions_with_alias(account):
    findings = find_go1x.scan_region(boto3.Session(), REGION)
    got = sorted((f.function, f.version, f.runtime, f.aliases, f.replacement) for f in findings)
    assert got == [
        ("legacy-java", "$LATEST", "java8", "", "java8.al2"),
        ("orders-go", "$LATEST", "go1.x", "", "provided.al2023"),
        ("orders-go", "1", "go1.x", "live", "provided.al2023"),
    ]


def test_exit_code_and_csv(account, tmp_path, capsys):
    out = tmp_path / "found.csv"
    assert find_go1x.main(["--regions", REGION, "--csv", str(out)]) == 1
    lines = out.read_text().splitlines()
    assert lines[0].startswith("region,function,version,runtime")
    assert len(lines) == 4
    assert "orders-go:1  go1.x -> provided.al2023 (aliases: live)" in capsys.readouterr().out


def test_clean_account_exits_zero(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    with mock_lambda():
        assert find_go1x.main(["--regions", REGION]) == 0
