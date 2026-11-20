"""Run the prescription assistant from a terminal.

    python -m rxagent "What is the status of RX-1002 and has it been dispensed?"
    python -m rxagent --approve ask "Cancel RX-1003: the patient had a cough on ramipril."

The API key is read from ANTHROPIC_API_KEY by the SDK; it is never printed.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys

import anthropic

from .loop import AgentResult, Decision, LoopConfig, deny_all, run
from .rx_service import RxService


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
        for c in t.calls:
            flag = "error" if c.is_error else "ok"
            approval = "" if c.approved is None else (" approved" if c.approved else " NOT approved")
            print(f"    tool: {c.name}({json.dumps(c.args)[:80]}) -> {flag}{approval} {c.ms:.1f} ms")
    u = result.usage()
    cost = result.cost_usd(model)
    print(f"\noutcome={result.outcome}  turns={len(result.turns)}  input={u['input_tokens']} "
          f"cache_write={u['cache_creation_input_tokens']} cache_read={u['cache_read_input_tokens']} "
          f"output={u['output_tokens']}" + (f"  cost=${cost:.4f}" if cost is not None else ""))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="rxagent")
    p.add_argument("prompt")
    p.add_argument("--model", default="claude-opus-5-5")
    p.add_argument("--effort", default="medium", choices=["low", "medium", "high", "xhigh", "max"])
    p.add_argument("--approve", default="no", choices=["no", "ask"], help="how state-changing tools are approved")
    p.add_argument("--log", action="store_true", help="print the JSON audit events to stderr")
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO if a.log else logging.WARNING, stream=sys.stderr, format="%(message)s")

    client = anthropic.Anthropic()  # ANTHROPIC_API_KEY from the environment
    result = run(client, RxService.with_sample_data(), a.prompt,
                 approver=ask_on_terminal if a.approve == "ask" else deny_all,
                 cfg=LoopConfig(model=a.model, effort=a.effort))
    print_trace(result, a.model)
    print("\n" + (result.text or f"[no answer: {result.outcome} {result.stop_details or ''}]"))
    return 0 if result.outcome == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())
