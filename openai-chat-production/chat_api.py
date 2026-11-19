"""Calling the OpenAI Chat Completions API from Python, as of September 2024.

Tested with openai==1.44.1. Covers:
  * a client with explicit timeout and retries
  * a pinned model snapshot
  * a tool-calling loop with strict schemas, argument validation and a step limit
  * structured output into a Pydantic model, with refusals and truncation reported
  * streaming with token usage
  * Batch API request lines and result parsing
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator, Literal, Optional, Type

import openai
from openai import OpenAI
from pydantic import BaseModel, ValidationError

log = logging.getLogger("chat_api")

# Pin a dated snapshot. On 10 Sep 2024 the "gpt-4o" alias still pointed to
# gpt-4o-2024-05-13; the 2024-08-06 snapshot is cheaper and adds Structured Outputs.
MODEL = "gpt-4o-2024-08-06"


def make_client(timeout: float = 60.0, max_retries: int = 3, **kwargs: Any) -> OpenAI:
    """Client with a deliberate timeout (the SDK default is 10 minutes) and retries.

    The SDK retries connection errors, 408, 409, 429 and 5xx with backoff and
    honours retry-after. The API key comes from OPENAI_API_KEY unless passed.
    """
    return OpenAI(timeout=timeout, max_retries=max_retries, **kwargs)


# ---------------------------------------------------------------- tools


@dataclass
class Tool:
    name: str
    args_model: Type[BaseModel]
    func: Callable[[BaseModel], Any]
    description: str = ""

    def schema(self) -> dict:
        return openai.pydantic_function_tool(
            self.args_model, name=self.name, description=self.description or None
        )


@dataclass
class ToolRun:
    answer: Optional[str]
    steps: int
    calls: list[tuple[str, str]] = field(default_factory=list)  # (tool, outcome)
    stopped: Literal["answered", "step_limit"] = "answered"


def run_with_tools(
    client: OpenAI,
    messages: list[dict],
    tools: list[Tool],
    model: str = MODEL,
    max_steps: int = 5,
) -> ToolRun:
    """Loop until the model answers or max_steps model calls have been made.

    Tool errors and invalid arguments go back to the model as tool results
    instead of crashing the request, so it can correct itself.
    """
    by_name = {t.name: t for t in tools}
    messages = list(messages)
    calls: list[tuple[str, str]] = []
    for step in range(1, max_steps + 1):
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=[t.schema() for t in tools],
            parallel_tool_calls=False,  # strict schemas need this in Sep 2024
            temperature=0,
        )
        msg = resp.choices[0].message
        if not msg.tool_calls:
            return ToolRun(msg.content, step, calls)
        messages.append(msg.model_dump(exclude_none=True))
        for tc in msg.tool_calls:
            content, outcome = _call_tool(by_name, tc.function.name, tc.function.arguments)
            calls.append((tc.function.name, outcome))
            log.info("tool=%s outcome=%s", tc.function.name, outcome)
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": content})
    return ToolRun(None, max_steps, calls, stopped="step_limit")


def _call_tool(by_name: dict[str, Tool], name: str, raw_args: str) -> tuple[str, str]:
    tool = by_name.get(name)
    if tool is None:
        return json.dumps({"error": f"unknown tool {name}"}), "unknown_tool"
    try:
        args = tool.args_model.model_validate_json(raw_args)
    except ValidationError as e:
        return json.dumps({"error": "invalid arguments", "detail": e.errors(include_url=False)}, default=str), "invalid_args"
    try:
        result = tool.func(args)
    except Exception as e:  # report to the model, keep the details in our logs
        log.exception("tool %s failed", name)
        return json.dumps({"error": f"{type(e).__name__}"}), "tool_error"
    return json.dumps(result, default=str), "ok"


# ---------------------------------------------------------------- structured output


@dataclass
class Parsed:
    status: Literal["ok", "refused", "truncated", "filtered"]
    value: Optional[BaseModel] = None
    detail: Optional[str] = None


def extract(client: OpenAI, schema: Type[BaseModel], system: str, text: str,
            model: str = MODEL, max_tokens: int = 1000) -> Parsed:
    try:
        resp = client.beta.chat.completions.parse(
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": text}],
            response_format=schema,
            temperature=0,
            max_tokens=max_tokens,
        )
    except openai.LengthFinishReasonError:
        return Parsed("truncated", detail=f"hit max_tokens={max_tokens}")
    except openai.ContentFilterFinishReasonError:
        return Parsed("filtered")
    msg = resp.choices[0].message
    if msg.refusal:
        return Parsed("refused", detail=msg.refusal)
    return Parsed("ok", value=msg.parsed)


# ---------------------------------------------------------------- streaming


@dataclass
class StreamResult:
    text: str = ""
    finish_reason: Optional[str] = None
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None


def stream_text(client: OpenAI, messages: list[dict], on_delta: Callable[[str], None],
                model: str = MODEL) -> StreamResult:
    """Stream text to on_delta and return the full text with token usage.

    With include_usage the final chunk has empty choices and carries usage.
    """
    out = StreamResult()
    parts: list[str] = []
    stream = client.chat.completions.create(
        model=model, messages=messages, stream=True, stream_options={"include_usage": True}
    )
    for chunk in stream:
        if chunk.usage:
            out.prompt_tokens = chunk.usage.prompt_tokens
            out.completion_tokens = chunk.usage.completion_tokens
        for choice in chunk.choices:
            if choice.delta.content:
                parts.append(choice.delta.content)
                on_delta(choice.delta.content)
            if choice.finish_reason:
                out.finish_reason = choice.finish_reason
    out.text = "".join(parts)
    return out


# ---------------------------------------------------------------- batch


def batch_lines(items: dict[str, list[dict]], model: str = MODEL, **body: Any) -> Iterator[str]:
    """JSONL request lines for the Batch API, one per custom_id."""
    for custom_id, messages in items.items():
        yield json.dumps({
            "custom_id": custom_id,
            "method": "POST",
            "url": "/v1/chat/completions",
            "body": {"model": model, "messages": messages, **body},
        })


def read_batch_results(lines: Iterator[str]) -> dict[str, dict]:
    """Map custom_id to {"ok": bool, "content" or "error"}. Output order is not guaranteed."""
    results: dict[str, dict] = {}
    for line in lines:
        if not line.strip():
            continue
        rec = json.loads(line)
        resp, err = rec.get("response"), rec.get("error")
        if err or not resp or resp.get("status_code") != 200:
            results[rec["custom_id"]] = {"ok": False, "error": err or (resp or {}).get("body")}
        else:
            results[rec["custom_id"]] = {"ok": True,
                                         "content": resp["body"]["choices"][0]["message"]["content"]}
    return results


def submit_batch(client: OpenAI, jsonl_path: str) -> str:
    """Upload a JSONL file and start a batch; returns the batch id to poll."""
    with open(jsonl_path, "rb") as f:
        upload = client.files.create(file=f, purpose="batch")
    batch = client.batches.create(input_file_id=upload.id, endpoint="/v1/chat/completions",
                                  completion_window="24h")
    return batch.id
