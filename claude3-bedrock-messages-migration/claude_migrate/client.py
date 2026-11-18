"""A small client for Claude 3 on Bedrock using InvokeModel and InvokeModelWithResponseStream."""
from __future__ import annotations

import json
import logging

import boto3
from botocore.config import Config

from .legacy import prefill_of
from .response import Result, from_message, from_stream

log = logging.getLogger("claude_migrate")

SONNET = "anthropic.claude-3-sonnet-20240229-v1:0"
HAIKU = "anthropic.claude-3-haiku-20240307-v1:0"

# Throttling is the usual failure on a new model; let botocore back off and retry.
RETRY = Config(retries={"max_attempts": 8, "mode": "adaptive"}, read_timeout=120)


class ClaudeOnBedrock:
    def __init__(self, model_id: str = SONNET, client=None, region: str = "us-east-1"):
        self.model_id = model_id
        self.client = client or boto3.client("bedrock-runtime", region_name=region, config=RETRY)

    def invoke(self, body: dict) -> Result:
        response = self.client.invoke_model(modelId=self.model_id, body=json.dumps(body),
                                            contentType="application/json", accept="application/json")
        result = from_message(json.loads(response["body"].read()), prefill_of(body))
        log.info("model=%s in=%d out=%d stop=%s", self.model_id, result.input_tokens, result.output_tokens,
                 result.stop_reason)
        return result

    def stream(self, body: dict) -> Result:
        response = self.client.invoke_model_with_response_stream(
            modelId=self.model_id, body=json.dumps(body), contentType="application/json", accept="application/json")
        events = (json.loads(part["chunk"]["bytes"]) for part in response["body"] if "chunk" in part)
        return from_stream(events, prefill_of(body))
