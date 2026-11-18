"""Microsoft Agent Framework agent with a history provider that writes to a file.

    python lab/agents/agent_framework_agent.py start|resend <state directory> <stand-in base URL>

The framework has no call that continues an interrupted run of a single agent, so there is no resume
action here: the only recovery is to send the task again on the same session.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any, Sequence

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from tools import INSTRUCTIONS, TASK, TOOLS  # noqa: E402

from agent_framework import Agent, BaseHistoryProvider, Message  # noqa: E402
from agent_framework.openai import OpenAIChatClient  # noqa: E402


class FileHistory(BaseHistoryProvider):
    """Conversation history in one JSON file per session, written atomically."""

    def __init__(self, directory: str) -> None:
        super().__init__("file-history")
        self.directory = directory

    def path(self, session_id: str | None) -> str:
        return os.path.join(self.directory, f"agent-framework-{session_id}.json")

    async def get_messages(self, session_id: str | None, *, state: dict[str, Any] | None = None, **kwargs: Any) -> list[Message]:
        if not os.path.exists(self.path(session_id)):
            return []
        with open(self.path(session_id), encoding="utf-8") as handle:
            return [Message.from_dict(item) for item in json.load(handle)]

    async def save_messages(self, session_id: str | None, messages: Sequence[Message], *, state: dict[str, Any] | None = None, **kwargs: Any) -> None:
        stored = [m.to_dict() for m in await self.get_messages(session_id)] + [m.to_dict() for m in messages]
        temporary = self.path(session_id) + ".tmp"
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(stored, handle)
        os.replace(temporary, self.path(session_id))


async def main(action: str, state: str, url: str) -> None:
    client = OpenAIChatClient(model_id="stand-in", api_key="not-a-real-key", base_url=f"{url}/v1")
    agent = Agent(client, INSTRUCTIONS, name="orders", tools=TOOLS, context_providers=[FileHistory(state)])
    session = agent.create_session(session_id="order-O-1001")
    response = await agent.run(TASK, session=session)
    print(response.text)


if __name__ == "__main__":
    asyncio.run(main(*sys.argv[1:4]))
