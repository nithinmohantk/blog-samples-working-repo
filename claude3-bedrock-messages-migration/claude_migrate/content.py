"""Content blocks for Claude 3 messages: text and images."""
from __future__ import annotations

import base64

IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}


def text_block(text: str) -> dict:
    return {"type": "text", "text": text}


def image_block(data: bytes, media_type: str) -> dict:
    """An image as Claude 3 takes it on Bedrock: base64 in the request body, no URLs."""
    if media_type not in IMAGE_TYPES:
        raise ValueError(f"unsupported media type {media_type}")
    return {"type": "image", "source": {"type": "base64", "media_type": media_type,
                                        "data": base64.b64encode(data).decode("ascii")}}


def user_message(*blocks: dict) -> dict:
    return {"role": "user", "content": list(blocks)}
