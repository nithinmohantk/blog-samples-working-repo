"""Turn a Claude 2 Text Completions request into a Claude 3 Messages request.

A Text Completions prompt is one string:  "<system>\\n\\nHuman: ...\\n\\nAssistant: ..."
The Messages API takes a top-level `system` string and a list of alternating
user and assistant messages. Text after the final "Assistant:" is a prefill:
the start of the answer the caller wants the model to continue.
"""
from __future__ import annotations

import re

HUMAN, ASSISTANT = "\n\nHuman:", "\n\nAssistant:"
ANTHROPIC_VERSION = "bedrock-2023-05-31"
_TURN = re.compile(r"(\n\nHuman:|\n\nAssistant:)")


class PromptFormatError(ValueError):
    pass


def parse_prompt(prompt: str) -> tuple[str | None, list[dict]]:
    """Return (system, messages). Consecutive turns from the same role are merged."""
    parts = _TURN.split(prompt)
    system = parts[0].strip() or None
    if len(parts) < 3:
        raise PromptFormatError("no '\\n\\nHuman:' turn found")
    messages: list[dict] = []
    for marker, text in zip(parts[1::2], parts[2::2]):
        role = "user" if marker == HUMAN else "assistant"
        text = text.strip()
        if messages and messages[-1]["role"] == role:
            messages[-1]["content"] += "\n\n" + text
        else:
            messages.append({"role": role, "content": text})
    if messages[0]["role"] != "user":
        raise PromptFormatError("the first turn must be Human")
    if parts[-2] != ASSISTANT:
        raise PromptFormatError("the prompt must end with '\\n\\nAssistant:'")
    # An empty final "Assistant:" just asks for the answer; text there is a prefill and stays.
    if messages[-1]["role"] == "assistant" and not messages[-1]["content"]:
        messages.pop()
    for m in messages:
        if not m["content"]:
            raise PromptFormatError(f"empty {m['role']} turn")
    return system, messages


def convert_body(old: dict) -> dict:
    """Map a Text Completions request body to a Messages request body."""
    system, messages = parse_prompt(old["prompt"])
    new: dict = {"anthropic_version": ANTHROPIC_VERSION, "max_tokens": old["max_tokens_to_sample"],
                 "messages": [{"role": m["role"], "content": [{"type": "text", "text": m["content"]}]} for m in messages]}
    if system:
        new["system"] = system
    # "\n\nHuman:" was a stop sequence because the model wrote both sides; the Messages API ends turns itself.
    stops = [s for s in old.get("stop_sequences", []) if s.strip() != "Human:"]
    if stops:
        new["stop_sequences"] = stops
    for key in ("temperature", "top_p", "top_k"):
        if key in old:
            new[key] = old[key]
    return new


def prefill_of(body: dict) -> str:
    """The prefill text, if the last message is from the assistant."""
    last = body["messages"][-1]
    if last["role"] != "assistant":
        return ""
    return "".join(block["text"] for block in last["content"] if block["type"] == "text")
