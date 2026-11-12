"""invoke_client.py - calling the agent on AgentCore Runtime and ending the session."""
import json
import uuid

import boto3

AGENT_RUNTIME_ARN = "arn:aws:bedrock-agentcore:eu-west-1:111122223333:runtime/order_agent-AbCdEf1234"

client = boto3.client("bedrock-agentcore")
session_id = f"order-chat-{uuid.uuid4()}"      # at least 33 characters; one ID maps to one microVM


def ask(prompt: str) -> dict:
    response = client.invoke_agent_runtime(
        agentRuntimeArn=AGENT_RUNTIME_ARN,
        qualifier="DEFAULT",
        runtimeSessionId=session_id,
        payload=json.dumps({"prompt": prompt}).encode(),
    )
    return json.loads(response["response"].read())


def end_conversation() -> None:
    # Without this the microVM idles until the idle timeout and its memory keeps billing.
    client.stop_runtime_session(
        agentRuntimeArn=AGENT_RUNTIME_ARN,
        qualifier="DEFAULT",
        runtimeSessionId=session_id,
    )
