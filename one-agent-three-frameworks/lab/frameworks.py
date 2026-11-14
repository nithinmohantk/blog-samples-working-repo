"""The same agent, built four ways. Each builder returns an async function that takes the user's message and
returns the agent's final text.

With hardened=False nothing is configured beyond the model endpoint, the instructions and the tools: every
limit, retry and error policy is the framework's default. With hardened=True each builder adds the few settings
that make the four behave alike: a cap of eight model calls, tool failures reported to the model without their
detail, arguments checked against the function's types, and retries on the one client that has none.
"""
from __future__ import annotations

from typing import Awaitable, Callable, Sequence

INSTRUCTIONS = "You are a support agent for an online shop. Use the tools to look up and refund orders. Be brief."
MAX_MODEL_CALLS = 8
TOOL_FAILED = "The tool failed. Do not retry; tell the user it could not be done."
Run = Callable[[str], Awaitable[str]]


def agent_framework(openai_url: str, gemini_url: str, tools: Sequence[Callable], hardened: bool = False) -> Run:
    """Microsoft Agent Framework, Chat Completions client."""
    from agent_framework import Agent
    from agent_framework.openai import OpenAIChatCompletionClient

    settings = {"function_invocation_configuration": {"max_iterations": MAX_MODEL_CALLS}} if hardened else {}
    client = OpenAIChatCompletionClient("stand-in", api_key="not-a-real-key", base_url=openai_url, **settings)
    agent = Agent(client, INSTRUCTIONS, name="support", tools=list(tools))

    async def run(message: str) -> str:
        return (await agent.run(message)).text

    return run


def langgraph(openai_url: str, gemini_url: str, tools: Sequence[Callable], hardened: bool = False) -> Run:
    """LangGraph's prebuilt ReAct agent over langchain-openai."""
    from langchain_openai import ChatOpenAI
    from langgraph.prebuilt import ToolNode, create_react_agent

    model = ChatOpenAI(model="stand-in", api_key="not-a-real-key", base_url=openai_url)
    # One model call and one tool step are two graph steps, so eight model calls need a limit of sixteen.
    config = {"recursion_limit": 2 * MAX_MODEL_CALLS} if hardened else {}
    agent = create_react_agent(model, ToolNode(list(tools), handle_tool_errors=TOOL_FAILED) if hardened else list(tools), prompt=INSTRUCTIONS)

    async def run(message: str) -> str:
        state = await agent.ainvoke({"messages": [("user", message)]}, config=config)
        return str(state["messages"][-1].content)

    return run


def _adk(model, tools: Sequence[Callable], hardened: bool) -> Run:
    import pydantic
    from google.adk.agents import LlmAgent
    from google.adk.agents.run_config import RunConfig
    from google.adk.runners import InMemoryRunner
    from google.genai import types

    settings: dict = {}
    run_config = None
    if hardened:
        # ADK passes the model's arguments to the function as they arrive. validate_call checks them first.
        tools = [pydantic.validate_call(tool) for tool in tools]
        settings["on_tool_error_callback"] = lambda tool, arguments, context, error: {"error": TOOL_FAILED}
        run_config = RunConfig(max_llm_calls=MAX_MODEL_CALLS)
    agent = LlmAgent(name="support", model=model, instruction=INSTRUCTIONS, tools=list(tools), **settings)
    runner = InMemoryRunner(agent=agent, app_name="lab")

    async def run(message: str) -> str:
        session = await runner.session_service.create_session(app_name="lab", user_id="user")
        text = ""
        content = types.Content(role="user", parts=[types.Part(text=message)])
        async for event in runner.run_async(user_id="user", session_id=session.id, new_message=content, run_config=run_config):
            if event.is_final_response() and event.content and event.content.parts:
                text = "".join(part.text or "" for part in event.content.parts)
        return text

    return run


def adk_gemini(openai_url: str, gemini_url: str, tools: Sequence[Callable], hardened: bool = False) -> Run:
    """Google ADK with its native Gemini model class, pointed at the stand-in's Gemini endpoint."""
    import os

    from google.adk.models import Gemini
    from google.genai import types

    os.environ.setdefault("GOOGLE_API_KEY", "not-a-real-key")
    retry = types.HttpRetryOptions(attempts=3, initial_delay=0.2, max_delay=1.0, http_status_codes=[429, 500, 502, 503, 504]) if hardened else None
    return _adk(Gemini(model="gemini-stand-in", base_url=gemini_url, retry_options=retry), tools, hardened)


def adk_litellm(openai_url: str, gemini_url: str, tools: Sequence[Callable], hardened: bool = False) -> Run:
    """Google ADK through its LiteLLM adapter, which is how it reaches OpenAI-compatible endpoints."""
    import litellm
    from google.adk.models.lite_llm import LiteLlm

    litellm.suppress_debug_info = True
    return _adk(LiteLlm(model="openai/stand-in", api_base=openai_url, api_key="not-a-real-key"), tools, hardened)


FRAMEWORKS: dict[str, Callable[..., Run]] = {
    "Agent Framework": agent_framework,
    "LangGraph": langgraph,
    "ADK (Gemini API)": adk_gemini,
    "ADK (LiteLLM)": adk_litellm,
}
