"""Bedrock calls checked with botocore's Stubber.

The Stubber validates every request against the service model shipped with
botocore, so a wrong parameter name or shape fails here. It does not prove
the service accepts the values (model ids, ARNs, quotas): no AWS account was
used.
"""

import hashlib
import json
from pathlib import Path

import boto3
import pytest
from botocore.stub import ANY, Stubber

from pipeline import bedrock_clients as bc
from pipeline.dataset_gate import run_gate

DATA = Path(__file__).resolve().parents[1] / "data"
ACCOUNT = "111122223333"

SETTINGS = bc.Settings(
    data_region="eu-west-1",
    training_regions=frozenset({"us-east-1"}),
    base_model_id="amazon.nova-micro-v1:0:128k",
    role_arn=f"arn:aws:iam::{ACCOUNT}:role/bedrock-customization",
    output_s3_uri="s3://example-training-output/jobs/",
    kms_key_arn=f"arn:aws:kms:us-east-1:{ACCOUNT}:key/00000000-0000-0000-0000-000000000000",
    knowledge_base_id="KBFIXTURE1",
    generation_model_arn=f"arn:aws:bedrock:eu-west-1:{ACCOUNT}:inference-profile/eu.amazon.nova-lite-v1:0",
    guardrail_id="gr0fixture01",
    guardrail_version="3",
)
HYPER = {"epochCount": "2", "learningRate": "0.00001", "learningRateWarmupSteps": "1"}


def _client(service, region):
    return boto3.client(service, region_name=region, aws_access_key_id="x", aws_secret_access_key="x")


@pytest.fixture
def certified(tmp_path):
    out = tmp_path / "train.jsonl"
    result = run_gate(DATA / "training/train_source.jsonl", out, min_records=6)
    return out, result.certificate()


def test_customization_job_request_matches_service_model(certified):
    dataset, cert = certified
    bedrock = _client("bedrock", "us-east-1")
    digest = hashlib.sha256(dataset.read_bytes()).hexdigest()
    with Stubber(bedrock) as stub:
        stub.add_response(
            "create_model_customization_job",
            {"jobArn": f"arn:aws:bedrock:us-east-1:{ACCOUNT}:model-customization-job/abc123"},
            {
                "jobName": "ie-guidance-ft-20260620",
                "customModelName": "ie-guidance-ft-20260620-model",
                "roleArn": SETTINGS.role_arn,
                "clientRequestToken": digest[:32],
                "baseModelIdentifier": "amazon.nova-micro-v1:0:128k",
                "customizationType": "FINE_TUNING",
                "customModelKmsKeyId": SETTINGS.kms_key_arn,
                "trainingDataConfig": {"s3Uri": "s3://example-training-input/train.jsonl"},
                "outputDataConfig": {"s3Uri": SETTINGS.output_s3_uri},
                "hyperParameters": HYPER,
                "jobTags": [{"key": "dataset-sha256", "value": digest}, {"key": "personal-data", "value": "none"}],
            },
        )
        arn = bc.submit_customization(bedrock, SETTINGS, cert, dataset,
                                      "s3://example-training-input/train.jsonl", "ie-guidance-ft-20260620", HYPER)
        stub.assert_no_pending_responses()
    assert arn.endswith("abc123")


def test_customization_refused_outside_training_region(certified):
    dataset, cert = certified
    with pytest.raises(bc.PolicyError, match="not an approved training Region"):
        bc.submit_customization(_client("bedrock", "eu-west-1"), SETTINGS, cert, dataset, "s3://b/k", "j", HYPER)


def test_customization_refused_when_dataset_changed_after_gate(certified):
    dataset, cert = certified
    dataset.write_text(dataset.read_text() + json.dumps({"late": "addition"}) + "\n")
    with pytest.raises(bc.PolicyError, match="changed after it passed the gate"):
        bc.submit_customization(_client("bedrock", "us-east-1"), SETTINGS, cert, dataset, "s3://b/k", "j", HYPER)


def test_hyperparameters_outside_documented_range_are_refused(certified):
    dataset, cert = certified
    with pytest.raises(bc.PolicyError, match="epochCount=8"):
        bc.submit_customization(_client("bedrock", "us-east-1"), SETTINGS, cert, dataset, "s3://b/k", "j",
                                {**HYPER, "epochCount": "8"})
    with pytest.raises(bc.PolicyError, match="batchSize"):
        bc.check_hyperparameters({"batchSize": "8"})


def _rag_response(guardrail_action="NONE"):
    return {
        "output": {"text": "Record what was shared, with whom, when and on what basis."},
        "citations": [{
            "generatedResponsePart": {"textResponsePart": {"text": "Record what was shared", "span": {"start": 0, "end": 22}}},
            "retrievedReferences": [{
                "content": {"text": "When a service shares information..."},
                "location": {"type": "S3", "s3Location": {"uri": "s3://example-corpus/im-standards-summary.md"}},
                "metadata": {"doc_id": "DOC-IM-01", "version": "2024"},
            }],
        }],
        "guardrailAction": guardrail_action,
        "sessionId": "s-1",
    }


def test_ask_sends_filter_and_guardrail_and_returns_doc_ids():
    runtime = _client("bedrock-agent-runtime", "eu-west-1")
    with Stubber(runtime) as stub:
        stub.add_response("retrieve_and_generate", _rag_response(), {
            "input": {"text": "What is recorded when information is shared?"},
            "retrieveAndGenerateConfiguration": ANY,
        })
        answer = bc.ask(runtime, SETTINGS, "What is recorded when information is shared?")
    assert answer.citations == ("DOC-IM-01",) and not answer.refused


def test_ask_full_request_validates_against_service_model():
    runtime = _client("bedrock-agent-runtime", "eu-west-1")
    captured = {}
    runtime.meta.events.register("before-parameter-build.bedrock-agent-runtime.RetrieveAndGenerate",
                                 lambda params, **kw: captured.update(params))
    with Stubber(runtime) as stub:
        stub.add_response("retrieve_and_generate", _rag_response("INTERVENED"))
        answer = bc.ask(runtime, SETTINGS, "q")
    kb = captured["retrieveAndGenerateConfiguration"]["knowledgeBaseConfiguration"]
    assert kb["generationConfiguration"]["guardrailConfiguration"] == {"guardrailId": "gr0fixture01", "guardrailVersion": "3"}
    assert kb["retrievalConfiguration"]["vectorSearchConfiguration"]["filter"]["andAll"][0] == \
        {"equals": {"key": "status", "value": "current"}}
    assert answer.refused


def test_ask_refuses_to_run_outside_data_region():
    with pytest.raises(bc.PolicyError, match="must run in eu-west-1"):
        bc.ask(_client("bedrock-agent-runtime", "us-east-1"), SETTINGS, "q")


def test_ask_retries_throttling_then_succeeds(monkeypatch):
    monkeypatch.setattr(bc.time, "sleep", lambda s: None)
    runtime = _client("bedrock-agent-runtime", "eu-west-1")
    with Stubber(runtime) as stub:
        stub.add_client_error("retrieve_and_generate", "ThrottlingException", http_status_code=429)
        stub.add_response("retrieve_and_generate", _rag_response())
        assert bc.ask(runtime, SETTINGS, "q").citations == ("DOC-IM-01",)
        stub.assert_no_pending_responses()


def test_ask_does_not_retry_validation_errors():
    runtime = _client("bedrock-agent-runtime", "eu-west-1")
    with Stubber(runtime) as stub:
        stub.add_client_error("retrieve_and_generate", "ValidationException", http_status_code=400)
        with pytest.raises(Exception, match="ValidationException"):
            bc.ask(runtime, SETTINGS, "q")


def test_guardrail_request_matches_service_model():
    bedrock = _client("bedrock", "eu-west-1")
    request = bc.guardrail_request("ie-guidance-assistant", f"arn:aws:kms:eu-west-1:{ACCOUNT}:key/x")
    with Stubber(bedrock) as stub:
        stub.add_response("create_guardrail", {
            "guardrailId": "gr0fixture01", "guardrailArn": f"arn:aws:bedrock:eu-west-1:{ACCOUNT}:guardrail/gr0fixture01",
            "version": "DRAFT", "createdAt": "2026-06-19T10:00:00Z"}, request)
        bedrock.create_guardrail(**request)
        stub.assert_no_pending_responses()


def test_guardrail_patterns_have_no_lookaround_and_catch_fixture_identifiers():
    import re
    for entry in bc.guardrail_request("n", "k")["sensitiveInformationPolicyConfig"]["regexesConfig"]:
        assert "(?<" not in entry["pattern"] and "(?=" not in entry["pattern"] and "(?!" not in entry["pattern"]
    patterns = [re.compile(e["pattern"]) for e in
                bc.guardrail_request("n", "k")["sensitiveInformationPolicyConfig"]["regexesConfig"]]
    for sample in ("000000000000000017", "0000000017", "1234567T", "6433435IH"):
        assert any(p.search(f"id {sample} here") for p in patterns), sample


def test_stubber_does_reject_a_malformed_request():
    """Guards the claim that these tests check shapes: a misspelt key must fail."""
    from botocore.exceptions import ParamValidationError
    bedrock = _client("bedrock", "eu-west-1")
    request = bc.guardrail_request("n", "k")
    request["sensitiveInformationPolicyConfig"]["regexesConfig"][0]["regex"] = request[
        "sensitiveInformationPolicyConfig"]["regexesConfig"][0].pop("pattern")
    with Stubber(bedrock) as stub:
        stub.add_response("create_guardrail", {"guardrailId": "g", "guardrailArn": "a" * 20,
                                               "version": "DRAFT", "createdAt": "2026-06-19T10:00:00Z"})
        with pytest.raises(ParamValidationError):
            bedrock.create_guardrail(**request)
