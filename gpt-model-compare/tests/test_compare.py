import json

import httpx
import pytest
from openai import OpenAI

import models as m
from compare import compare, run_one


def test_cost_arithmetic():
    assert m.cost("gpt-4", 1000, 1000) == pytest.approx(0.09)
    assert m.cost("gpt-4-1106-preview", 1000, 1000) == pytest.approx(0.04)
    assert m.cost("gpt-3.5-turbo-1106", 1000, 1000) == pytest.approx(0.003)
    assert m.monthly_cost("gpt-4-1106-preview", 100_000, 2000, 500) == 3500.0


def test_fits_checks_window_and_output_cap():
    assert m.fits("gpt-4-1106-preview", 100_000, 4_000)
    assert not m.fits("gpt-4-1106-preview", 100_000, 8_000)    # output cap 4,096
    assert not m.fits("gpt-4", 6_000, 4_000)                    # 8K window


def test_cheapest_that_fits():
    cands = ["gpt-3.5-turbo-1106", "gpt-4", "gpt-4-1106-preview"]
    assert m.cheapest_that_fits(cands, 2_000, 500) == "gpt-3.5-turbo-1106"
    assert m.cheapest_that_fits(cands, 50_000, 1_000) == "gpt-4-1106-preview"
    assert m.cheapest_that_fits(["gpt-4", "gpt-4-1106-preview"], 2_000, 500, need_json=True) == "gpt-4-1106-preview"
    assert m.cheapest_that_fits(["gpt-4"], 200_000, 10) is None


def fake_client(answers: dict[str, str], seen: list):
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body)
        model = body["model"]
        if model == "gpt-4":
            return httpx.Response(400, json={"error": {"message": "bad", "type": "invalid_request_error"}})
        return httpx.Response(200, json={
            "id": "chatcmpl-1", "object": "chat.completion", "created": 1705000000, "model": model,
            "system_fingerprint": "fp_test",
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": answers[model]}}],
            "usage": {"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150}})
    return OpenAI(api_key="test", base_url="https://api.test/v1", max_retries=0,
                  http_client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_run_sends_seed_temperature_and_json_mode_only_where_supported():
    seen = []
    client = fake_client({"gpt-3.5-turbo-1106": '{"intent": "refund"}', "gpt-4-1106-preview": '{"intent": "refund"}'}, seen)
    prompt = {"id": "p1", "user": "Classify as JSON: I want my money back", "json": True}
    r = run_one(client, "gpt-4-1106-preview", prompt)
    assert r.error is None and r.fingerprint == "fp_test"
    assert (r.input_tokens, r.output_tokens) == (120, 30)
    assert r.cost == pytest.approx(120 / 1000 * 0.01 + 30 / 1000 * 0.03)
    assert seen[-1]["seed"] == 7 and seen[-1]["temperature"] == 0
    assert seen[-1]["response_format"] == {"type": "json_object"}


def test_invalid_json_and_api_errors_are_reported():
    seen = []
    client = fake_client({"gpt-3.5-turbo-1106": "Sure! The intent is refund."}, seen)
    results = compare(client, ["gpt-3.5-turbo-1106", "gpt-4"], [{"id": "p1", "user": "Reply in JSON", "json": True}])
    by_model = {r.model: r for r in results}
    assert by_model["gpt-3.5-turbo-1106"].error == "invalid JSON"
    assert by_model["gpt-4"].error == "BadRequestError"
    assert "response_format" not in seen[-1]                     # gpt-4 has no JSON mode


def test_unknown_model_rejected():
    with pytest.raises(ValueError):
        compare(fake_client({}, []), ["gpt-5"], [])
