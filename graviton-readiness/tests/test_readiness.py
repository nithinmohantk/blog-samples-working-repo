import json
import urllib.error

import boto3
import pytest
from botocore.stub import Stubber

import check_images as ci
import check_wheels as cw

INDEX = "application/vnd.oci.image.index.v1+json"
MANIFEST = "application/vnd.oci.image.manifest.v1+json"


@pytest.fixture
def ecr():
    return boto3.client("ecr", region_name="eu-west-1", aws_access_key_id="x", aws_secret_access_key="x")


def get_image_params(repo, tag):
    return {"repositoryName": repo, "imageIds": [{"imageTag": tag}], "acceptedMediaTypes": ci.ACCEPT}


def index_response(repo, tag, platforms):
    manifests = [{"mediaType": MANIFEST, "digest": "sha256:" + str(i) * 64, "size": 1,
                  "platform": p} for i, p in enumerate(platforms)]
    return {"images": [{"registryId": "123456789012", "repositoryName": repo,
                        "imageId": {"imageTag": tag},
                        "imageManifest": json.dumps({"schemaVersion": 2, "mediaType": INDEX, "manifests": manifests}),
                        "imageManifestMediaType": INDEX}], "failures": []}


def test_multi_arch_index_is_ready_and_attestations_ignored(ecr):
    plats = [{"os": "linux", "architecture": "amd64"},
             {"os": "linux", "architecture": "arm64", "variant": "v8"},
             {"os": "unknown", "architecture": "unknown"}]
    with Stubber(ecr) as st:
        st.add_response("batch_get_image", index_response("orders-api", "1.4", plats), get_image_params("orders-api", "1.4"))
        rows = ci.report(ecr, ["orders-api:1.4"])
    assert rows == [{"image": "orders-api:1.4", "platforms": ["linux/amd64", "linux/arm64/v8"], "arm64": True}]


def test_amd64_only_index_needs_build(ecr):
    with Stubber(ecr) as st:
        st.add_response("batch_get_image", index_response("billing", "2", [{"os": "linux", "architecture": "amd64"}]),
                        get_image_params("billing", "2"))
        rows = ci.report(ecr, ["billing:2"])
    assert rows[0]["arm64"] is False and rows[0]["platforms"] == ["linux/amd64"]


def test_single_platform_manifest_reads_config_architecture(ecr, monkeypatch):
    manifest = {"schemaVersion": 2, "mediaType": MANIFEST,
                "config": {"mediaType": "application/vnd.oci.image.config.v1+json", "digest": "sha256:" + "c" * 64, "size": 1},
                "layers": []}
    resp = {"images": [{"repositoryName": "legacy", "imageId": {"imageTag": "1"},
                        "imageManifest": json.dumps(manifest), "imageManifestMediaType": MANIFEST}], "failures": []}
    monkeypatch.setattr(ci, "_fetch_json", lambda url: {"os": "linux", "architecture": "arm64"})
    with Stubber(ecr) as st:
        st.add_response("batch_get_image", resp, get_image_params("legacy", "1"))
        st.add_response("get_download_url_for_layer",
                        {"downloadUrl": "https://example.invalid/blob", "layerDigest": "sha256:" + "c" * 64},
                        {"repositoryName": "legacy", "layerDigest": "sha256:" + "c" * 64})
        rows = ci.report(ecr, ["legacy:1"])
    assert rows[0]["arm64"] is True


def test_missing_tag_is_reported_not_raised(ecr):
    with Stubber(ecr) as st:
        st.add_response("batch_get_image", {"images": [], "failures": [
            {"imageId": {"imageTag": "9"}, "failureCode": "ImageNotFound", "failureReason": "Requested image not found"}]},
            get_image_params("gone", "9"))
        rows = ci.report(ecr, ["gone:9"])
    assert rows[0]["arm64"] is False and "ImageNotFound" in rows[0]["error"]


def test_bad_reference_rejected(ecr):
    with pytest.raises(ValueError):
        ci.report(ecr, ["no-tag"])


def test_parse_pins_handles_extras_markers_and_options():
    text = """
    # comment
    -r base.txt
    numpy==2.2.3
    uvicorn[standard]==0.34.0 ; python_version >= "3.9"
    psycopg2==2.9.10 \\
        --hash=sha256:abc
    requests>=2
    """
    assert cw.parse_pins(text) == [("numpy", "2.2.3"), ("uvicorn", "0.34.0"), ("psycopg2", "2.9.10")]


@pytest.mark.parametrize("files,expected", [
    (["pkg-1.0-py3-none-any.whl", "pkg-1.0.tar.gz"], "pure"),
    (["np-2.2.3-cp313-cp313-manylinux_2_17_aarch64.manylinux2014_aarch64.whl"], "aarch64"),
    (["np-2.2.3-cp313-cp313-musllinux_1_2_aarch64.whl"], "aarch64"),
    (["ext-1.0-cp313-cp313-manylinux_2_17_x86_64.whl", "ext-1.0.tar.gz"], "sdist-only"),
    (["ext-1.0-cp313-cp313-win_amd64.whl"], "x86-only"),
    ([], "none"),
])
def test_classify(files, expected):
    assert cw.classify(files) == expected


def test_check_reports_404():
    def fetch(name, version):
        if name == "private-lib":
            raise urllib.error.HTTPError("u", 404, "Not Found", {}, None)
        return ["x-1-py3-none-any.whl"]
    rows = cw.check([("private-lib", "1.0"), ("x", "1")], fetch)
    assert [r["status"] for r in rows] == ["not-on-pypi", "pure"]
