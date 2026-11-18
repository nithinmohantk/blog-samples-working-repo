"""Response shapes as documented for the Messages API on Bedrock (bedrock-2023-05-31).

Synthetic content; the shapes are checked by parsing them with Anthropic's SDK 0.20.0.
"""
MESSAGE = {
    "id": "msg_01XFDUDYJgAACzvnptvVoYEL", "type": "message", "role": "assistant",
    "model": "claude-3-sonnet-20240229",
    "content": [{"type": "text", "text": "Summary: the patient was discharged on day three."}],
    "stop_reason": "end_turn", "stop_sequence": None,
    "usage": {"input_tokens": 412, "output_tokens": 14},
}

STREAM = [
    {"type": "message_start", "message": {"id": "msg_01", "type": "message", "role": "assistant", "content": [],
                                          "model": "claude-3-haiku-20240307", "stop_reason": None, "stop_sequence": None,
                                          "usage": {"input_tokens": 25, "output_tokens": 1}}},
    {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
    {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Three"}},
    {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": " findings."}},
    {"type": "content_block_stop", "index": 0},
    {"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": None}, "usage": {"output_tokens": 4}},
    {"type": "message_stop", "amazon-bedrock-invocationMetrics": {"inputTokenCount": 25, "outputTokenCount": 4,
                                                                  "invocationLatency": 412, "firstByteLatency": 203}},
]
