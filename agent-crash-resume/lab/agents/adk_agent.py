"""Google ADK agent with a SQLite session service and resumability switched on.

    python lab/agents/adk_agent.py start|resume|resend <state directory> <stand-in base URL>

start   runs the task in a new session.
resume  continues the interrupted invocation by passing its invocation id and no new message.
resend  sends the task again in the same session.
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from tools import INSTRUCTIONS, TASK, TOOLS  # noqa: E402

APP, USER, SESSION = "orders", "user", "order-O-1001"


async def main(action: str, state: str, url: str) -> None:
    from google.adk.agents import LlmAgent
    from google.adk.apps import App, ResumabilityConfig
    from google.adk.models import Gemini
    from google.adk.runners import Runner
    from google.adk.sessions.sqlite_session_service import SqliteSessionService
    from google.genai import types

    os.environ.setdefault("GOOGLE_API_KEY", "not-a-real-key")
    agent = LlmAgent(name="orders", model=Gemini(model="gemini-stand-in", base_url=url), instruction=INSTRUCTIONS, tools=TOOLS)
    sessions = SqliteSessionService(os.path.join(state, "adk.sqlite"))
    runner = Runner(app=App(name=APP, root_agent=agent, resumability_config=ResumabilityConfig(is_resumable=True)), session_service=sessions)
    if action == "start":
        await sessions.create_session(app_name=APP, user_id=USER, session_id=SESSION)
    arguments: dict = {"user_id": USER, "session_id": SESSION}
    if action == "resume":
        stored = await sessions.get_session(app_name=APP, user_id=USER, session_id=SESSION)
        arguments["invocation_id"] = stored.events[-1].invocation_id
    else:
        arguments["new_message"] = types.Content(role="user", parts=[types.Part(text=TASK)])
    text = ""
    async for event in runner.run_async(**arguments):
        if event.is_final_response() and event.content and event.content.parts:
            text = "".join(part.text or "" for part in event.content.parts)
    print(text)


if __name__ == "__main__":
    asyncio.run(main(*sys.argv[1:4]))
