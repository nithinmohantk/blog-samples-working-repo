import json

import boto3
import pytest
from botocore.stub import Stubber

import evaluate as ev

SYSTEM = "Classify the query as BILLING, TECHNICAL, SALES or OTHER. Reply with one word."


def ok(text, latency=120, tin=40, tout=2, reasoning=False):
    content = [{"text": text}]
    if reasoning:
        content.insert(0, {"reasoningContent": {"reasoningText": {"text": "thinking"}}})
    return {
        "output": {"message": {"role": "assistant", "content": content}},
        "stopReason": "end_turn",
        "usage": {"inputTokens": tin, "outputTokens": tout, "totalTokens": tin + tout},
        "metrics": {"latencyMs": latency},
    }


def expected_params(model, text, reasoning=None):
    p = {
        "modelId": model,
        "system": [{"text": SYSTEM}],
        "messages": [{"role": "user", "content": [{"text": text}]}],
        "inferenceConfig": {"maxTokens": 10, "temperature": 0.0},
    }
    if reasoning:
        p["additionalModelRequestFields"] = {"reasoningConfig": {"type": "enabled", "maxReasoningEffort": reasoning}}
        p["inferenceConfig"] = {"maxTokens": 4000}
    return p


@pytest.fixture
def client():
    return boto3.client("bedrock-runtime", region_name="us-east-1",
                        aws_access_key_id="x", aws_secret_access_key="x")


CASES = [
    {"input": "I was charged twice", "expected": "BILLING"},
    {"input": "The app crashes on login", "expected": "TECHNICAL"},
    {"input": "Do you offer volume discounts?", "expected": "SALES"},
]


def test_accuracy_latency_tokens_and_cost(client, monkeypatch):
    model = "us.amazon.nova-micro-v1:0"
    with Stubber(client) as st:
        st.add_response("converse", ok("BILLING", 100), expected_params(model, CASES[0]["input"]))
        st.add_response("converse", ok("technical.", 140), expected_params(model, CASES[1]["input"]))
        st.add_response("converse", ok("OTHER", 900), expected_params(model, CASES[2]["input"]))
        r = ev.evaluate(client, model, CASES, SYSTEM)
    assert (r.cases, r.correct, r.errors) == (3, 2, 0)
    assert r.accuracy == pytest.approx(2 / 3)
    assert r.p50_ms == 140 and r.p95_ms == 900
    assert (r.input_tokens, r.output_tokens) == (120, 6)
    assert r.cost_usd() == pytest.approx((120 * 0.035 + 6 * 0.14) / 1e6)
    assert r.mistakes == [{"input": CASES[2]["input"], "expected": "SALES", "got": "OTHER"}]


def test_reasoning_blocks_are_ignored_and_config_sent(client):
    model = "global.amazon.nova-2-lite-v1:0"
    with Stubber(client) as st:
        st.add_response("converse", ok("BILLING", tout=300, reasoning=True),
                        expected_params(model, CASES[0]["input"], reasoning="low"))
        r = ev.evaluate(client, model, CASES[:1], SYSTEM, reasoning="low")
    assert r.correct == 1
    assert r.output_tokens == 300         # reasoning tokens are billed as output


def test_throttling_is_retried_then_errors_are_counted(client, monkeypatch):
    monkeypatch.setattr(ev.time, "sleep", lambda s: None)
    model = "us.amazon.nova-lite-v1:0"
    with Stubber(client) as st:
        st.add_client_error("converse", "ThrottlingException", http_status_code=429)
        st.add_response("converse", ok("BILLING"), expected_params(model, CASES[0]["input"]))
        st.add_client_error("converse", "AccessDeniedException", http_status_code=403)
        r = ev.evaluate(client, model, CASES[:2], SYSTEM)
    assert (r.correct, r.errors) == (1, 1)
    assert r.accuracy == 1.0              # errors are excluded from accuracy, reported separately
    assert r.mistakes[0]["error"] == "AccessDeniedException"


def test_unknown_price_returns_none():
    assert ev.ModelReport("some.other-model").cost_usd() is None


def test_load_cases_validates(tmp_path):
    good = tmp_path / "c.jsonl"
    good.write_text(json.dumps(CASES[0]) + "\n\n")
    assert ev.load_cases(str(good)) == [CASES[0]]
    bad = tmp_path / "b.jsonl"
    bad.write_text(json.dumps({"input": "x"}) + "\n")
    with pytest.raises(ValueError):
        ev.load_cases(str(bad))
