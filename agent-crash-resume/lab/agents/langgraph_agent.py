"""LangGraph agent with a SQLite checkpointer.

    python lab/agents/langgraph_agent.py start|resume|resend <state directory> <stand-in base URL>

start   runs the task on a new thread.
resume  invokes the same thread with no input, which continues from the last checkpoint.
resend  sends the task again on the same thread, as a caller that only knows "it did not finish" would.
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from tools import INSTRUCTIONS, TASK, TOOLS  # noqa: E402

THREAD = {"configurable": {"thread_id": "order-O-1001"}}


async def main(action: str, state: str, url: str) -> None:
    from langchain.agents import create_agent
    from langchain_openai import ChatOpenAI
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    model = ChatOpenAI(model="stand-in", api_key="not-a-real-key", base_url=f"{url}/v1", max_retries=0)
    async with AsyncSqliteSaver.from_conn_string(os.path.join(state, "langgraph.sqlite")) as checkpointer:
        agent = create_agent(model, TOOLS, system_prompt=INSTRUCTIONS, checkpointer=checkpointer)
        given = None if action == "resume" else {"messages": [("user", TASK)]}
        result = await agent.ainvoke(given, THREAD)
        print(result["messages"][-1].content)


if __name__ == "__main__":
    asyncio.run(main(*sys.argv[1:4]))
