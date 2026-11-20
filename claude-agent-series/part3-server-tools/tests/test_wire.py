"""The real SDK client against a mock HTTP transport: checks what goes on the wire with anthropic 2.3.0."""
from __future__ import annotations

import json

import anthropic
import httpx2 as httpx  # anthropic 2.x still uses the httpx2 package

from rxagent.loop import run
from rxagent.rx_service import RxService


def test_request_on_the_wire_uses_api_version_2026_10_21_and_bearer_auth():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, headers={"request-id": "req_test"}, json={
            "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
            "stop_reason": "end_turn", "stop_sequence": None,
            "content": [{"type": "text", "text": "ok"}],
            "usage": {"input_tokens": 10, "output_tokens": 2,
                      "server_tool_use": {"web_search_requests": 0, "web_fetch_requests": 0}}})

    client = anthropic.Anthropic(api_key="test-key", default_headers={"anthropic-workspace-id": "wrkspc_test"},
                                 http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    result = run(client, RxService.with_sample_data(), "Status of RX-1002?")
    req = seen[0]
    body = json.loads(req.content)
    assert req.headers["anthropic-version"] == "2026-10-21"
    assert req.headers["authorization"] == "Bearer test-key" and "x-api-key" not in req.headers
    assert req.headers["anthropic-workspace-id"] == "wrkspc_test"
    # removed in 2026-10-21: sending any of them is a 400, even at default values
    assert not {"temperature", "top_p", "top_k"} & body.keys()
    assert {t.get("type") for t in body["tools"]} >= {"web_search_20260318", "web_fetch_20260318"}
    assert result.turns[0].request_id == "req_test"
