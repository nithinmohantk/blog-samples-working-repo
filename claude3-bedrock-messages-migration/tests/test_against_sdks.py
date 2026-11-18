"""Check requests and responses against Anthropic's own Bedrock client and botocore, as of March 2024."""
import io
import json

import anthropic
import boto3
import httpx
import pytest
from botocore.awsrequest import AWSResponse
from botocore.stub import Stubber

from claude_migrate.client import HAIKU, SONNET, ClaudeOnBedrock
from claude_migrate.legacy import convert_body
from claude_migrate.response import from_message, from_stream

from .eventstream import stream
from .fixtures import MESSAGE, STREAM

OLD = {"prompt": "You summarise clinical notes in one sentence.\n\nHuman: <note>Admitted with chest pain...</note>"
                 "\n\nAssistant:", "max_tokens_to_sample": 300, "stop_sequences": ["\n\nHuman:"], "temperature": 0.2}


def sdk(handler):
    return anthropic.AnthropicBedrock(aws_access_key="AKIDEXAMPLE", aws_secret_key="secret", aws_region="us-east-1",
                                      http_client=httpx.Client(transport=httpx.MockTransport(handler)))


def capture(seen):
    def handler(request):
        seen["path"], seen["body"] = request.url.path, json.loads(request.content)
        return httpx.Response(200, json=MESSAGE)
    return handler


def test_old_body_is_what_the_sdk_sends_for_text_completions():
    seen = {}
    sdk(capture(seen)).completions.create(model="anthropic.claude-v2:1", prompt=OLD["prompt"],
                                          max_tokens_to_sample=300, stop_sequences=["\n\nHuman:"], temperature=0.2)
    assert seen["path"] == "/model/anthropic.claude-v2:1/invoke"
    assert {k: v for k, v in seen["body"].items() if k != "anthropic_version"} == OLD


def test_converted_body_is_exactly_what_the_sdk_sends_for_messages():
    new = convert_body(OLD)
    seen = {}
    sdk(capture(seen)).messages.create(model=SONNET, max_tokens=new["max_tokens"], system=new["system"],
                                       messages=new["messages"], temperature=new["temperature"])
    assert seen["path"] == f"/model/{SONNET}/invoke"
    assert seen["body"] == new


def test_sdk_and_our_parser_read_the_response_the_same_way():
    seen = {}
    message = sdk(capture(seen)).messages.create(model=SONNET, max_tokens=10, messages=[{"role": "user", "content": "x"}])
    ours = from_message(MESSAGE)
    assert ours.text == message.content[0].text
    assert (ours.input_tokens, ours.output_tokens, ours.stop_reason) == (message.usage.input_tokens,
                                                                       message.usage.output_tokens, message.stop_reason)
    assert ours.legacy() == {"completion": MESSAGE["content"][0]["text"], "stop_reason": "stop_sequence"}


def test_invoke_through_botocore_stubber():
    client = boto3.client("bedrock-runtime", region_name="us-east-1", aws_access_key_id="x", aws_secret_access_key="x")
    body = convert_body(OLD)
    with Stubber(client) as stub:
        stub.add_response("invoke_model",
                          {"body": io.BytesIO(json.dumps(MESSAGE).encode()), "contentType": "application/json"},
                          {"modelId": SONNET, "body": json.dumps(body), "contentType": "application/json",
                           "accept": "application/json"})
        result = ClaudeOnBedrock(SONNET, client).invoke(body)
    assert result.text.startswith("Summary:") and result.output_tokens == 14


class _Raw:
    def __init__(self, data):
        self._data = data

    def stream(self, **_):
        yield self._data


def test_stream_parsed_identically_by_botocore_and_the_anthropic_sdk():
    raw = stream(STREAM)
    # botocore: real event-stream decoding, fed through a before-send hook
    client = boto3.client("bedrock-runtime", region_name="us-east-1", aws_access_key_id="x", aws_secret_access_key="x")
    client.meta.events.register("before-send.bedrock-runtime.InvokeModelWithResponseStream",
                                lambda request, **_: AWSResponse(request.url, 200, {}, _Raw(raw)))
    ours = ClaudeOnBedrock(HAIKU, client).stream({"anthropic_version": "bedrock-2023-05-31", "max_tokens": 50,
                                                  "messages": [{"role": "user", "content": "x"}]})
    # Anthropic SDK: its own Bedrock event-stream decoder, fed the same bytes
    events = list(sdk(lambda request: httpx.Response(200, content=raw, headers={
        "content-type": "application/vnd.amazon.eventstream"})).messages.create(
        model=HAIKU, max_tokens=50, messages=[{"role": "user", "content": "x"}], stream=True))
    sdk_text = "".join(e.delta.text for e in events if e.type == "content_block_delta")
    assert [e.type for e in events] == [e["type"] for e in STREAM]
    assert ours.text == sdk_text == "Three findings."
    assert (ours.input_tokens, ours.output_tokens, ours.stop_reason) == (25, 4, "end_turn")
    assert ours.extra["firstByteLatency"] == 203


def test_from_stream_keeps_a_prefill():
    assert from_stream(STREAM, prefill="Result: ").text == "Result: Three findings."
