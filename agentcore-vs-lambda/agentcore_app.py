"""
agentcore_app.py
Host 2: Amazon Bedrock AgentCore Runtime. Each session gets its own microVM, so
process memory is session memory for as long as the session lives.
"""
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from starlette.responses import JSONResponse

from agent_core import InvalidRequest, run_turn

app = BedrockAgentCoreApp()

# Safe as a module global only because one microVM serves exactly one session.
# It is gone when the session ends. Persist anything that must outlive it.
_history: list = []


@app.entrypoint
def invoke(payload: dict, context):
    try:
        answer = run_turn(_history, payload.get("prompt"))
    except InvalidRequest as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    return {"answer": answer, "sessionId": context.session_id, "messagesInSession": len(_history)}


if __name__ == "__main__":
    app.run()   # serves POST /invocations and GET /ping on 0.0.0.0:8080
