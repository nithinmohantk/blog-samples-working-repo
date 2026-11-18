"""Read Claude 3 Messages responses, whole or streamed, and offer the old shape to old callers."""
from __future__ import annotations

from dataclasses import dataclass, field

# Text Completions on Bedrock reported "stop_sequence" or "max_tokens".
LEGACY_STOP = {"end_turn": "stop_sequence", "stop_sequence": "stop_sequence", "max_tokens": "max_tokens"}


@dataclass
class Result:
    text: str
    stop_reason: str | None
    stop_sequence: str | None
    input_tokens: int
    output_tokens: int
    extra: dict = field(default_factory=dict)

    def legacy(self) -> dict:
        """{'completion', 'stop_reason'} as a Claude 2 caller expects it."""
        return {"completion": self.text, "stop_reason": LEGACY_STOP.get(self.stop_reason, self.stop_reason)}


def from_message(payload: dict, prefill: str = "") -> Result:
    """A whole response. The model continues after a prefill; it does not repeat it."""
    text = "".join(block.get("text", "") for block in payload["content"] if block["type"] == "text")
    usage = payload.get("usage", {})
    return Result(prefill + text, payload.get("stop_reason"), payload.get("stop_sequence"),
                  usage.get("input_tokens", 0), usage.get("output_tokens", 0))


def from_stream(events, prefill: str = "") -> Result:
    """Fold the decoded stream events (message_start ... message_stop) into one Result."""
    pieces, stop_reason, stop_sequence, input_tokens, output_tokens, extra = [prefill], None, None, 0, 0, {}
    for event in events:
        kind = event.get("type")
        if kind == "message_start":
            input_tokens = event["message"]["usage"].get("input_tokens", 0)
        elif kind == "content_block_delta" and event["delta"].get("type") == "text_delta":
            pieces.append(event["delta"]["text"])
        elif kind == "message_delta":
            stop_reason = event["delta"].get("stop_reason")
            stop_sequence = event["delta"].get("stop_sequence")
            output_tokens = event.get("usage", {}).get("output_tokens", output_tokens)
        elif kind == "message_stop" and "amazon-bedrock-invocationMetrics" in event:
            extra = event["amazon-bedrock-invocationMetrics"]
    return Result("".join(pieces), stop_reason, stop_sequence, input_tokens, output_tokens, extra)
