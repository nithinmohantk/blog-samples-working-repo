"""
lambda_handler.py
Host 1: AWS Lambda behind a function URL or API Gateway. Execution environments are
reused across callers, so conversation state has to live outside the function.
"""
import json
import os
import re
import time

import boto3
from boto3.dynamodb.conditions import Attr

from agent_core import InvalidRequest, run_turn

table = boto3.resource("dynamodb").Table(os.environ["SESSIONS_TABLE"])
SESSION_ID = re.compile(r"^[A-Za-z0-9-]{33,128}$")
SESSION_TTL_SECONDS = 3600


def handler(event, context):
    try:
        body = json.loads(event.get("body") or "{}")
        session_id = body.get("sessionId", "")
        if not SESSION_ID.match(session_id):
            raise InvalidRequest("sessionId must be 33 to 128 letters, digits or hyphens")

        item = table.get_item(Key={"sessionId": session_id}, ConsistentRead=True).get("Item")
        history = json.loads(item["history"]) if item else []
        version = int(item["version"]) if item else 0

        answer = run_turn(history, body.get("prompt"))

        # Optimistic lock: two concurrent turns on one session must not overwrite each other.
        table.put_item(
            Item={
                "sessionId": session_id,
                "history": json.dumps(history),
                "version": version + 1,
                "expiresAt": int(time.time()) + SESSION_TTL_SECONDS,
            },
            ConditionExpression=Attr("version").not_exists() | Attr("version").eq(version),
        )
        return _response(200, {"answer": answer, "sessionId": session_id})
    except InvalidRequest as exc:
        return _response(400, {"error": str(exc)})
    except json.JSONDecodeError:
        return _response(400, {"error": "request body must be JSON"})
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        return _response(409, {"error": "another request is in progress for this session"})


def _response(status: int, body: dict) -> dict:
    return {"statusCode": status, "headers": {"Content-Type": "application/json"}, "body": json.dumps(body)}
