import json

import httpx
import pytest
from openai import BadRequestError

import aoai

INVOICE = {"supplier": "Contoso Ltd", "invoice_number": "INV-1042", "currency": "EUR", "total": 240.0,
           "lines": [{"description": "Licences", "quantity": 4, "unit_price": 60.0}]}


def client_with(handler, seen):
    def wrapped(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)
    return aoai.make_client(endpoint="https://contoso.openai.azure.com", token_provider=lambda: "entra-token",
                            max_retries=0, http_client=httpx.Client(transport=httpx.MockTransport(wrapped)))


def completion(content=None, finish="stop", refusal=None):
    return httpx.Response(200, json={
        "id": "c1", "object": "chat.completion", "created": 1731800000, "model": "gpt-4o-2024-08-06",
        "choices": [{"index": 0, "finish_reason": finish,
                     "message": {"role": "assistant", "content": content, "refusal": refusal}}],
        "usage": {"prompt_tokens": 210, "completion_tokens": 64, "total_tokens": 274}})


def test_request_uses_deployment_path_ga_version_bearer_token_and_schema():
    seen = []
    c = client_with(lambda r: completion(json.dumps(INVOICE)), seen)
    out = aoai.extract_invoice(c, "invoices-gpt4o", "Invoice INV-1042 from Contoso Ltd ...")
    req = seen[0]
    assert req.url.path == "/openai/deployments/invoices-gpt4o/chat/completions"
    assert req.url.params["api-version"] == "2024-10-21"
    assert req.headers["authorization"] == "Bearer entra-token"
    assert "api-key" not in req.headers
    body = json.loads(req.content)
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["strict"] is True
    assert out.status == "ok" and out.invoice.total == 240.0 and out.invoice.lines[0].quantity == 4
    assert (out.prompt_tokens, out.completion_tokens) == (210, 64)


def test_refusal_is_reported():
    out = aoai.extract_invoice(client_with(lambda r: completion(None, refusal="I can't help with that."), []),
                               "d", "text")
    assert out.status == "refused" and "can't" in out.detail


def test_completion_content_filter_is_reported():
    out = aoai.extract_invoice(client_with(lambda r: completion(None, finish="content_filter"), []), "d", "text")
    assert out.status == "filtered"


def test_prompt_content_filter_400_is_reported():
    err = {"error": {"message": "The response was filtered", "type": None, "param": "prompt",
                     "code": "content_filter", "status": 400}}
    out = aoai.extract_invoice(client_with(lambda r: httpx.Response(400, json=err), []), "d", "text")
    assert out.status == "filtered"


def test_other_400_errors_are_raised():
    err = {"error": {"message": "bad", "type": "invalid_request_error", "code": "invalid_value"}}
    with pytest.raises(BadRequestError):
        aoai.extract_invoice(client_with(lambda r: httpx.Response(400, json=err), []), "d", "text")


def test_truncated_answer_is_reported_without_parsing():
    seen = []
    def handler(r):
        return completion('{"supplier": "Cont', finish="length")
    out = aoai.extract_invoice(client_with(handler, seen), "d", "text")
    assert out.status == "truncated"
