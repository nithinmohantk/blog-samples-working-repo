"""The real SDK client against a mock HTTP transport: checks what goes on the wire."""
from __future__ import annotations

import json

import anthropic
import httpx2 as httpx  # anthropic 1.x uses the httpx2 package

from rxagent.loop import run
from rxagent.rx_service import RxService


def test_request_on_the_wire():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, headers={"request-id": "req_test"}, json={
            "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
            "stop_reason": "end_turn", "stop_sequence": None,
            "content": [{"type": "text", "text": "ok"}],
            "usage": {"input_tokens": 10, "output_tokens": 2}})

    client = anthropic.Anthropic(api_key="test-key", http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    result = run(client, RxService.with_sample_data(), "Status of RX-1002?")
    body = json.loads(seen[0].content)
    assert seen[0].headers["anthropic-version"] == "2023-06-01"
    assert body["thinking"] == {"type": "adaptive", "display": "summarized"}
    assert body["output_config"] == {"effort": "medium"} and body["cache_control"] == {"type": "ephemeral"}
    assert "temperature" not in body and "tool_choice" not in body  # Opus 5.5 rejects forced tool choice
    assert result.turns[0].request_id == "req_test"
