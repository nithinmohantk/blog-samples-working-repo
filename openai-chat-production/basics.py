"""First calls, multi-turn conversations and image input with Chat Completions.

Tested with openai==1.44.1.
"""
from __future__ import annotations

import base64
import mimetypes
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional

from openai import OpenAI

from chat_api import MODEL


@dataclass
class Answer:
    text: Optional[str]
    finish_reason: str
    prompt_tokens: int
    completion_tokens: int


def ask(client: OpenAI, question: str, system: str = "You are a concise technical assistant.",
        model: str = MODEL, max_tokens: int = 500) -> Answer:
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": question}],
        max_tokens=max_tokens,
    )
    choice = resp.choices[0]
    return Answer(choice.message.content, choice.finish_reason,
                  resp.usage.prompt_tokens, resp.usage.completion_tokens)


@dataclass
class Conversation:
    """The API is stateless: the application sends the history on every call.

    max_turns caps how many user/assistant pairs are resent, so cost and
    latency do not grow without limit. The system prompt is always kept.
    """
    client: OpenAI
    system: str
    model: str = MODEL
    max_turns: int = 10
    history: list[dict] = field(default_factory=list)

    def send(self, text: str) -> str:
        self.history.append({"role": "user", "content": text})
        recent = self.history[-(2 * self.max_turns - 1):]
        resp = self.client.chat.completions.create(
            model=self.model, messages=[{"role": "system", "content": self.system}, *recent]
        )
        reply = resp.choices[0].message.content or ""
        self.history.append({"role": "assistant", "content": reply})
        return reply


def image_part(source: str, detail: Literal["low", "high", "auto"] = "auto") -> dict:
    """An image content part from an https URL or a local file.

    Local files are sent as a data URL with the file's real MIME type.
    detail="low" costs a fixed, small number of tokens; "high" costs more for large images.
    """
    if source.startswith("https://"):
        url = source
    else:
        path = Path(source)
        mime = mimetypes.guess_type(path.name)[0]
        if mime not in {"image/png", "image/jpeg", "image/gif", "image/webp"}:
            raise ValueError(f"unsupported image type: {path.suffix}")
        url = f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"
    return {"type": "image_url", "image_url": {"url": url, "detail": detail}}


def describe_image(client: OpenAI, source: str, prompt: str, model: str = MODEL,
                   detail: Literal["low", "high", "auto"] = "auto", max_tokens: int = 500) -> Answer:
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": [{"type": "text", "text": prompt}, image_part(source, detail)]}],
        max_tokens=max_tokens,
    )
    choice = resp.choices[0]
    return Answer(choice.message.content, choice.finish_reason,
                  resp.usage.prompt_tokens, resp.usage.completion_tokens)
