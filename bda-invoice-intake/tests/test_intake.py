"""Requests go through botocore's Stubber, which validates them against the
API models shipped with the pinned botocore release."""

import io
import json
from datetime import datetime, timezone

import boto3
import pytest
from botocore.response import StreamingBody
from botocore.stub import ANY, Stubber

import blueprint as bp
import intake

REGION = "us-east-1"
PROJECT = "arn:aws:bedrock:us-east-1:111122223333:data-automation-project/abc123"
PROFILE = "arn:aws:bedrock:us-east-1:111122223333:data-automation-profile/us.data-automation-v1"
BLUEPRINT_ARN = "arn:aws:bedrock:us-east-1:111122223333:blueprint/inv123"
NOW = datetime(2026, 2, 20, tzinfo=timezone.utc)


def client(name):
    return boto3.client(name, region_name=REGION, aws_access_key_id="x", aws_secret_access_key="x")


def body(obj):
    raw = json.dumps(obj).encode()
    return StreamingBody(io.BytesIO(raw), len(raw))


def test_invoice_blueprint_is_within_limits():
    assert bp.check_blueprint(bp.INVOICE) == []
    leaves = bp.leaf_fields(bp.INVOICE)
    assert len(leaves) == 13 and "line_items.unit_price" in leaves


def test_check_blueprint_reports_problems():
    bad = bp.build_blueprint("x", "y", [bp.Field("a/b", ""), bp.Field("n", "ok", type="date"),
                                        bp.Field("m", "ok", inference="guess")])
    problems = bp.check_blueprint(bad)
    assert any("contain no '/'" in p for p in problems)
    assert any("missing instruction" in p for p in problems)
    assert any("type must be" in p for p in problems)
    assert any("inferenceType" in p for p in problems)
    many = bp.build_blueprint("x", "y", [bp.Field(f"f{i}", "v") for i in range(101)])
    assert any("limit is 100" in p for p in bp.check_blueprint(many))


def test_create_blueprint_request_matches_model():
    c = client("bedrock-data-automation")
    with Stubber(c) as stub:
        stub.add_response("create_blueprint", {"blueprint": {
            "blueprintArn": BLUEPRINT_ARN, "schema": "{}", "type": "DOCUMENT",
            "creationTime": NOW, "lastModifiedTime": NOW, "blueprintName": "supplier-invoice"}},
            {"blueprintName": "supplier-invoice", "type": "DOCUMENT",
             "blueprintStage": "DEVELOPMENT", "schema": json.dumps(bp.INVOICE)})
        assert bp.create_blueprint(c, "supplier-invoice", bp.INVOICE) == BLUEPRINT_ARN


def test_create_blueprint_refuses_invalid_schema():
    with pytest.raises(ValueError, match="missing instruction"):
        bp.create_blueprint(None, "x", bp.build_blueprint("x", "y", [bp.Field("a", " ")]))


def test_submit_request_matches_model_and_is_idempotent():
    c = client("bedrock-data-automation-runtime")
    uri = "s3://ap-inbox/2026/02/inv-001.pdf"
    with Stubber(c) as stub:
        for _ in range(2):
            stub.add_response("invoke_data_automation_async",
                              {"invocationArn": "arn:aws:bedrock:us-east-1:111122223333:data-automation-invocation/j1"},
                              {"clientToken": ANY, "inputConfiguration": {"s3Uri": uri},
                               "outputConfiguration": {"s3Uri": "s3://ap-bda-output/"},
                               "dataAutomationConfiguration": {"dataAutomationProjectArn": PROJECT, "stage": "LIVE"},
                               "dataAutomationProfileArn": PROFILE,
                               "notificationConfiguration": {"eventBridgeConfiguration": {"eventBridgeEnabled": True}},
                               "encryptionConfiguration": {"kmsKeyId": "alias/ap-docs"}})
        args = dict(input_uri=uri, output_uri="s3://ap-bda-output/", project_arn=PROJECT,
                    profile_arn=PROFILE, kms_key_arn="alias/ap-docs")
        assert intake.submit(c, **args).endswith("/j1")
        assert intake.submit(c, **args).endswith("/j1")


def test_cost_matches_aws_pricing_examples():
    assert round(1000 * intake.cost_per_page(15), 2) == 40.00
    assert round(40 * intake.cost_per_page(20) + 10 * intake.cost_per_page(40), 2) == 2.05


CUSTOM = {
    "matched_blueprint": {"arn": BLUEPRINT_ARN, "name": "supplier-invoice", "confidence": 1.0},
    "inference_result": {"invoice_number": "INV-1001", "gross_total": 1230.0, "purchase_order_number": ""},
    "explainability_info": [{
        "invoice_number": {"success": True, "confidence": 0.98, "value": "INV-1001"},
        "gross_total": {"success": True, "confidence": 0.62, "value": 1230.0},
        "line_items": [{"unit_price": {"confidence": 0.91}}, {"unit_price": {"confidence": 0.4}}],
    }],
}


def test_route_flags_low_confidence_and_missing_fields():
    r = intake.route(CUSTOM, 0.85, {"invoice_number", "purchase_order_number"})
    assert r["low_confidence"] == ["gross_total", "line_items[1].unit_price"]
    assert r["missing_required"] == ["purchase_order_number"]
    assert r["needs_review"] is True
    assert intake.route(CUSTOM, 0.3, {"invoice_number"})["needs_review"] is False


EVENT = {"detail-type": "Bedrock Data Automation Job Succeeded", "source": "aws.bedrock",
         "detail": {"job_id": "25010344-03f7", "job_status": "SUCCESS", "semantic_modality": "Document",
                    "input_s3_object": {"s3_bucket": "ap-inbox", "name": "2026/02/inv-001.pdf"},
                    "output_s3_location": {"s3_bucket": "ap-bda-output", "name": "out"},
                    "error_message": ""}}


def test_handler_reads_metadata_and_queues_review(monkeypatch):
    monkeypatch.setenv("REVIEW_QUEUE_URL", "https://sqs.us-east-1.amazonaws.com/111122223333/ap-review")
    monkeypatch.setenv("REQUIRED_FIELDS", "invoice_number,gross_total")
    s3, sqs = client("s3"), client("sqs")
    meta_key = "out/25010344-03f7/0/job_metadata.json"
    meta = {"output_metadata": [{"segment_metadata": [
        {"custom_output_status": "MATCH",
         "custom_output_path": "s3://ap-bda-output/out/25010344-03f7/0/custom_output/0/result.json"},
        {"custom_output_status": "NO_MATCH"}]}]}
    with Stubber(s3) as s, Stubber(sqs) as q:
        s.add_response("list_objects_v2", {"Contents": [{"Key": "out/other/job_metadata.json"}, {"Key": meta_key}]},
                       {"Bucket": "ap-bda-output", "Prefix": "out/"})
        s.add_response("get_object", {"Body": body(meta)}, {"Bucket": "ap-bda-output", "Key": meta_key})
        s.add_response("get_object", {"Body": body(CUSTOM)},
                       {"Bucket": "ap-bda-output", "Key": "out/25010344-03f7/0/custom_output/0/result.json"})
        q.add_response("send_message", {"MessageId": "m1"},
                       {"QueueUrl": "https://sqs.us-east-1.amazonaws.com/111122223333/ap-review", "MessageBody": ANY})
        q.add_response("send_message", {"MessageId": "m2"},
                       {"QueueUrl": "https://sqs.us-east-1.amazonaws.com/111122223333/ap-review", "MessageBody": ANY})
        result = intake.handler(EVENT, s3=s3, sqs=sqs)
    assert result == {"job_id": "25010344-03f7", "documents": 1, "review": 2}


def test_handler_queues_failed_jobs(monkeypatch):
    monkeypatch.setenv("REVIEW_QUEUE_URL", "https://sqs.us-east-1.amazonaws.com/111122223333/ap-review")
    failed = {"detail": {**EVENT["detail"], "job_status": "CLIENT_ERROR", "error_message": "bad file"}}
    sqs = client("sqs")
    with Stubber(sqs) as q:
        q.add_response("send_message", {"MessageId": "m3"},
                       {"QueueUrl": "https://sqs.us-east-1.amazonaws.com/111122223333/ap-review", "MessageBody": ANY})
        assert intake.handler(failed, s3=object(), sqs=sqs) == {"job_id": "25010344-03f7", "documents": 0, "review": 1}
