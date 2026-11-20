"""Run the Agent SDK version from a terminal.

    python -m rxagent_sdk "What is the status of RX-1002, and has it been dispensed?"
    python -m rxagent_sdk --approve ask "Cancel RX-1003: the patient developed a dry cough on ramipril."

ANTHROPIC_API_KEY (and ANTHROPIC_WORKSPACE_ID for a multi-workspace key) are read
from the environment and passed to the Claude Code process; they are never printed.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
import warnings

from claude_agent_sdk import (
    AssistantMessage,
    CanUseToolShadowedWarning,
    ClaudeSDKError,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ThinkingBlock,
    ToolUseBlock,
    query,
)

from .agent import AuditLog, build_options, deny_all, prompt_stream
from .rx_service import RxService


async def ask_on_terminal(name: str, args: dict) -> bool:
    print(f"\n  APPROVAL NEEDED  {name} {json.dumps(args)}", flush=True)
    answer = await asyncio.to_thread(input, "  Approve? [y/N] ")
    return answer.strip().lower() == "y"


async def run(prompt: str, approve: str, model: str, effort: str, tool_search: bool) -> int:
    audit = AuditLog()
    options = build_options(RxService.with_sample_data(), ask_on_terminal if approve == "ask" else deny_all, audit,
                            model=model, effort=effort, tool_search=tool_search)
    started = time.perf_counter()
    turns: dict[str, int] = {}  # the SDK yields one AssistantMessage per content block; group by message_id
    exit_code = 1
    async for message in query(prompt=prompt_stream(prompt), options=options):  # read to the end; do not return early
        if isinstance(message, SystemMessage) and message.subtype == "init":
            tools = message.data.get("tools", [])
            print(f"session start  model={message.data.get('model')}  tools={tools}")
        elif isinstance(message, AssistantMessage):
            turn = turns.setdefault(message.message_id or str(len(turns)), len(turns) + 1)
            for block in message.content:
                if isinstance(block, ToolUseBlock):
                    print(f"turn {turn}  tool: {block.name}({json.dumps(block.input)[:80]})")
                elif isinstance(block, ThinkingBlock) and block.thinking:
                    print(f"turn {turn}  note: {block.thinking.strip()[:140]}")
                elif isinstance(block, TextBlock):
                    pass  # the final text arrives in the ResultMessage too
        elif isinstance(message, ResultMessage):
            u = message.usage or {}
            print(f"\nresult={message.subtype}  stop={message.stop_reason}  turns={message.num_turns}  "
                  f"wall={time.perf_counter() - started:.1f}s  api={message.duration_api_ms / 1000:.1f}s")
            print(f"input={u.get('input_tokens')} cache_write={u.get('cache_creation_input_tokens')} "
                  f"cache_read={u.get('cache_read_input_tokens')} output={u.get('output_tokens')}  "
                  f"cost=${(message.total_cost_usd or 0):.4f}  denials={len(message.permission_denials or [])}")
            for e in audit.events:
                print("  audit:", json.dumps(e))
            print("\n" + (message.result or f"[no answer: {message.errors}]"))
            exit_code = 0 if message.subtype == "success" and not message.is_error else 1
    return exit_code


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="rxagent_sdk")
    p.add_argument("prompt")
    p.add_argument("--model", default="claude-opus-5-5")
    p.add_argument("--effort", default="medium", choices=["low", "medium", "high", "xhigh", "max"])
    p.add_argument("--approve", default="no", choices=["no", "ask"])
    p.add_argument("--no-tool-search", action="store_true", help="load all tool definitions up front")
    p.add_argument("--log", action="store_true")
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO if a.log else logging.WARNING, stream=sys.stderr, format="%(message)s")
    # Intentional: the lookups are pre-approved, so they never reach can_use_tool. The audit hook sees every call.
    warnings.filterwarnings("ignore", category=CanUseToolShadowedWarning)
    try:
        return asyncio.run(run(a.prompt, a.approve, a.model, a.effort, not a.no_tool_search))
    except ClaudeSDKError as e:
        print(f"Agent SDK error: {type(e).__name__}: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
