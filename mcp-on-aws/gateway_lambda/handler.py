"""AWS Lambda target for an Amazon Bedrock AgentCore Gateway.

AgentCore Gateway speaks MCP to the client. For a Lambda target it invokes
this function with the tool arguments as the event, and puts the tool name in
context.client_context.custom["bedrockAgentCoreToolName"], prefixed with the
target name and a triple underscore. The function itself contains no MCP code.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from typing import Any, Callable

# Allow `sales_tools` to be packaged next to this file or one level up.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sales_tools  # noqa: E402

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

TOOL_NAME_DELIMITER = "___"

TOOLS: dict[str, Callable[..., dict[str, Any]]] = {
    "get_customer_summary": lambda args: sales_tools.get_customer_summary(
        args.get("customer_id")
    ),
    "list_customer_orders": lambda args: sales_tools.list_customer_orders(
        args.get("customer_id"),
        args.get("limit", 10),
        args.get("next_token"),
    ),
}


def _tool_name(context: Any) -> str:
    custom = getattr(getattr(context, "client_context", None), "custom", None) or {}
    qualified = custom.get("bedrockAgentCoreToolName", "")
    if TOOL_NAME_DELIMITER in qualified:
        return qualified.split(TOOL_NAME_DELIMITER, 1)[1]
    return qualified


def _log(level: int, message: str, **fields: Any) -> None:
    logger.log(level, json.dumps({"message": message, **fields}, default=str))


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    tool = _tool_name(context)
    request_id = getattr(context, "aws_request_id", None)
    handler = TOOLS.get(tool)
    if handler is None:
        _log(logging.WARNING, "unknown tool", tool=tool, request_id=request_id)
        return {"error": "UNKNOWN_TOOL", "message": f"Unknown tool: {tool}"}

    try:
        result = handler(event or {})
    except sales_tools.ToolInputError as exc:
        # Input errors go back to the model so it can correct the call.
        _log(logging.INFO, "invalid input", tool=tool, request_id=request_id, error=str(exc))
        return {"error": "INVALID_INPUT", "message": str(exc)}
    except Exception:  # noqa: BLE001 - never leak internals to the model
        logger.exception(json.dumps({"message": "tool failed", "tool": tool, "request_id": request_id}))
        return {"error": "INTERNAL_ERROR", "message": "The tool failed. Try again later."}

    _log(logging.INFO, "tool succeeded", tool=tool, request_id=request_id)
    return result
