"""Encode AWS event stream frames, the binary format InvokeModelWithResponseStream returns.

Frame: total length, headers length, prelude CRC32, headers, payload, message CRC32.
Each Bedrock frame is an event of type "chunk" whose JSON payload holds the model's
event, base64-encoded under "bytes".
"""
import base64
import binascii
import json
import struct


def _header(name: str, value: str) -> bytes:
    n, v = name.encode(), value.encode()
    return struct.pack(">B", len(n)) + n + b"\x07" + struct.pack(">H", len(v)) + v  # 7 = string


def frame(model_event: dict) -> bytes:
    payload = json.dumps({"bytes": base64.b64encode(json.dumps(model_event).encode()).decode()}).encode()
    headers = _header(":event-type", "chunk") + _header(":content-type", "application/json") + _header(":message-type", "event")
    total = 12 + len(headers) + len(payload) + 4
    prelude = struct.pack(">II", total, len(headers))
    prelude += struct.pack(">I", binascii.crc32(prelude) & 0xFFFFFFFF)
    body = prelude + headers + payload
    return body + struct.pack(">I", binascii.crc32(body) & 0xFFFFFFFF)


def stream(events: list[dict]) -> bytes:
    return b"".join(frame(e) for e in events)
