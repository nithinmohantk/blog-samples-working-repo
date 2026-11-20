"""Run the prescription assistant from a terminal.

    python -m rxagent "Is there any current safety communication about the medicine on RX-1003?"
    python -m rxagent --no-server-tools "What is the status of RX-1002 and has it been dispensed?"

The API key is read from ANTHROPIC_API_KEY by the SDK; it is never printed.
A key that can act on more than one workspace also needs ANTHROPIC_WORKSPACE_ID
(sent as the anthropic-workspace-id header); a workspace-scoped key does not.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys

import anthropic

from .loop import AgentResult, Decision, LoopConfig, deny_all, run
from .rx_service import RxService
from .tools import ServerToolPolicy


def ask_on_terminal(name: str, args: dict) -> Decision:
    print(f"\n  APPROVAL NEEDED  {name} {json.dumps(args)}")
    answer = input("  Approve? [y/N] ").strip().lower()
    return Decision(answer == "y", "approved on the terminal" if answer == "y" else "declined on the terminal")


def print_trace(result: AgentResult, model: str) -> None:
    for t in result.turns:
        u = t.usage
        print(f"turn {t.index}  stop={t.stop_reason:<9} in={u['input_tokens']:>5} "
              f"cache_write={u['cache_creation_input_tokens']:>5} cache_read={u['cache_read_input_tokens']:>5} "
              f"out={u['output_tokens']:>5}  request_id={t.request_id}")
        for note in t.notes:
            print(f"    note: {note.strip()[:150]}")
        for sc in t.server_calls:
            what = sc.input.get("query") or sc.input.get("url") or ""
            print(f"    server: {sc.name}({what[:70]!r}) -> {sc.outcome}{'  FLAGGED' if sc.flagged else ''}")
        for c in t.calls:
            flag = "error" if c.is_error else "ok"
            approval = "" if c.approved is None else (" approved" if c.approved else " NOT approved")
            print(f"    tool: {c.name}({json.dumps(c.args)[:80]}) -> {flag}{approval} {c.ms:.1f} ms")
    u = result.usage()
    cost = result.cost_usd(model)
    print(f"\noutcome={result.outcome}  turns={len(result.turns)}  input={u['input_tokens']} "
          f"cache_write={u['cache_creation_input_tokens']} cache_read={u['cache_read_input_tokens']} "
          f"output={u['output_tokens']}  searches={u['web_search_requests']} fetches={u['web_fetch_requests']}"
          + (f"  cost=${cost:.4f}" if cost is not None else ""))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="rxagent")
    p.add_argument("prompt")
    p.add_argument("--model", default="claude-opus-5-5")
    p.add_argument("--effort", default="medium", choices=["low", "medium", "high", "xhigh", "max"])
    p.add_argument("--approve", default="no", choices=["no", "ask"], help="how state-changing tools are approved")
    p.add_argument("--no-server-tools", action="store_true", help="client tools only, as in Part 1")
    p.add_argument("--log", action="store_true", help="print the JSON audit events to stderr")
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO if a.log else logging.WARNING, stream=sys.stderr, format="%(message)s")

    workspace = os.environ.get("ANTHROPIC_WORKSPACE_ID")
    client = anthropic.Anthropic(  # ANTHROPIC_API_KEY from the environment
        default_headers={"anthropic-workspace-id": workspace} if workspace else None)
    try:
        result = run(client, RxService.with_sample_data(), a.prompt,
                     approver=ask_on_terminal if a.approve == "ask" else deny_all,
                     cfg=LoopConfig(model=a.model, effort=a.effort,
                                    server_tools=None if a.no_server_tools else ServerToolPolicy()))
    except anthropic.APIStatusError as e:  # after the SDK's own retries
        print(f"API error {e.status_code} ({type(e).__name__}), request_id={e.request_id}: {e.message}", file=sys.stderr)
        return 2
    except anthropic.APIConnectionError as e:
        print(f"Could not reach the API: {e}", file=sys.stderr)
        return 2
    print_trace(result, a.model)
    print("\n" + (result.text or f"[no answer: {result.outcome} {result.stop_details or ''}]"))
    for title, url in result.sources:
        print(f"  source: {title} <{url}>")
    return 0 if result.outcome == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())
