"""
agent_core.py
The agent itself: a bounded tool loop over the Amazon Bedrock Converse API.
Nothing in this module knows whether it runs on Lambda or on AgentCore Runtime.
"""
import logging
import os

import boto3
from botocore.config import Config

logger = logging.getLogger(__name__)

MODEL_ID = os.environ["BEDROCK_MODEL_ID"]   # model or inference profile ID, set per environment
MAX_MODEL_CALLS = 6                          # hard stop for a model that keeps asking for tools
MAX_PROMPT_CHARS = 4000

SYSTEM = [{"text": "You answer order enquiries briefly. Use the tool to look up order status."}]
TOOL_CONFIG = {
    "tools": [{
        "toolSpec": {
            "name": "get_order_status",
            "description": "Returns the fulfilment status of an order.",
            "inputSchema": {"json": {
                "type": "object",
                "properties": {"order_id": {"type": "string", "description": "For example ORD-10042"}},
                "required": ["order_id"],
            }},
        }
    }]
}

bedrock = boto3.client(
    "bedrock-runtime",
    config=Config(retries={"mode": "adaptive", "max_attempts": 5}, read_timeout=120),
)


class InvalidRequest(ValueError):
    """The caller sent something the agent will not process."""


def get_order_status(order_id: str) -> dict:
    # Replace with a real lookup. Validate and authorise here: the model chooses the arguments.
    if not isinstance(order_id, str) or not order_id.startswith("ORD-"):
        raise InvalidRequest("order_id must look like ORD-10042")
    return {"order_id": order_id, "status": "SHIPPED"}


TOOLS = {"get_order_status": get_order_status}


def run_turn(history: list, prompt) -> str:
    """Run one user turn. Appends to history in place and returns the answer text."""
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > MAX_PROMPT_CHARS:
        raise InvalidRequest(f"prompt must be a non-empty string of at most {MAX_PROMPT_CHARS} characters")

    history.append({"role": "user", "content": [{"text": prompt}]})

    for _ in range(MAX_MODEL_CALLS):
        response = bedrock.converse(
            modelId=MODEL_ID,
            system=SYSTEM,
            messages=history,
            toolConfig=TOOL_CONFIG,
            inferenceConfig={"maxTokens": 1024, "temperature": 0.2},
        )
        message = response["output"]["message"]
        history.append(message)
        logger.info("model call usage=%s stop=%s", response.get("usage"), response["stopReason"])  # counts only

        if response["stopReason"] != "tool_use":
            return "".join(block.get("text", "") for block in message["content"])

        history.append({"role": "user", "content": [_run_tool(b["toolUse"]) for b in message["content"] if "toolUse" in b]})

    raise RuntimeError(f"agent did not finish within {MAX_MODEL_CALLS} model calls")


def _run_tool(tool_use: dict) -> dict:
    try:
        result = TOOLS[tool_use["name"]](**tool_use["input"])
        return {"toolResult": {"toolUseId": tool_use["toolUseId"], "content": [{"json": result}]}}
    except (KeyError, TypeError, InvalidRequest) as exc:
        # Tell the model the call failed so it can recover or apologise. Do not raise.
        return {"toolResult": {"toolUseId": tool_use["toolUseId"], "content": [{"text": str(exc)}], "status": "error"}}
