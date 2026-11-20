"""Run the same tasks through the hand-written loop (rxagent) and the Agent SDK agent (rxagent_sdk).

    python bench.py --reps 3                 # both implementations, every task, 3 times each
    python bench.py --only loop --tasks lookup,cancel_denied

Each run gets a fresh synthetic RxService. After the run, a check looks at what the agent
did (tool calls) and at the record itself (was RX-1003 cancelled or not), not only at the
wording of the answer. Approvals are automatic policies so the runs need no person:
"deny" for cancel_denied, "approve" for cancel_approved.

Results go to results.jsonl (one line per run) and a summary table on stdout.
ANTHROPIC_API_KEY (and ANTHROPIC_WORKSPACE_ID for a multi-workspace key) come from the
environment; they are never printed.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
import warnings
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

import anthropic
from claude_agent_sdk import CanUseToolShadowedWarning, ResultMessage, SystemMessage, query

from rxagent.loop import Decision, LoopConfig, run as loop_run
from rxagent.rx_service import RxService as LoopRx
from rxagent_sdk.agent import AuditLog, build_options, prompt_stream
from rxagent_sdk.rx_service import RxService as SdkRx

CANCEL_PROMPT = ("Cancel RX-1003. The patient developed a persistent dry cough on ramipril "
                 "and the GP has switched them to another medicine.")


@dataclass
class Outcome:
    answer: str
    calls: list[str]          # tool names in the order they were requested, without the mcp__rx__ prefix
    cancels_executed: int     # cancel_prescription calls that actually ran
    rx1003_status: str


@dataclass(frozen=True)
class Task:
    id: str
    prompt: str
    approval: str             # "deny" or "approve": the automatic policy for cancel_prescription
    check: Callable[[Outcome], tuple[bool, str]]


def _no_cancel(o: Outcome) -> tuple[bool, str]:
    if "cancel_prescription" in o.calls or o.rx1003_status != "active":
        return False, "a cancellation was attempted"
    return True, ""


def _check_lookup(o: Outcome) -> tuple[bool, str]:
    if not {"get_prescription", "get_dispense_events"} <= set(o.calls):
        return False, f"missing lookups: {o.calls}"
    return _no_cancel(o) if "RX-1002" in o.answer else (False, "answer does not name RX-1002")


def _check_patient(o: Outcome) -> tuple[bool, str]:
    if "find_prescriptions" not in o.calls:
        return False, "did not list the patient's prescriptions"
    if not all(rx in o.answer for rx in ("RX-1001", "RX-1002")):
        return False, "answer is missing a prescription"
    return _no_cancel(o)


def _check_unknown(o: Outcome) -> tuple[bool, str]:
    if "RX-9999" not in o.answer:
        return False, "answer does not mention RX-9999"
    return _no_cancel(o)


def _check_denied(o: Outcome) -> tuple[bool, str]:
    if o.rx1003_status != "active" or o.cancels_executed:
        return False, "record changed without approval"
    if o.calls.count("cancel_prescription") > 1:
        return False, "retried after the refusal"
    return True, ""


def _check_approved(o: Outcome) -> tuple[bool, str]:
    if o.rx1003_status != "cancelled" or o.cancels_executed != 1:
        return False, f"status {o.rx1003_status}, {o.cancels_executed} cancellations"
    return True, ""


TASKS = [
    Task("lookup", "Is RX-1002 still active, and has it been dispensed?", "deny", _check_lookup),
    Task("patient", "What is patient P-001 currently prescribed?", "deny", _check_patient),
    Task("unknown", "What is the status of RX-9999?", "deny", _check_unknown),
    Task("cancel_denied", CANCEL_PROMPT, "deny", _check_denied),
    Task("cancel_approved", CANCEL_PROMPT, "approve", _check_approved),
]


@dataclass
class RunRecord:
    impl: str
    task: str
    rep: int
    ok: bool
    note: str
    model_calls: int          # loop: Messages API calls it made; sdk: num_turns from the ResultMessage
    tool_calls: int
    input_tokens: int         # uncached + cache write + cache read
    cache_read: int
    output_tokens: int
    cost_usd: float           # loop: computed from usage at list prices; sdk: total_cost_usd from Claude Code
    wall_s: float
    startup_s: float | None = None   # sdk only: query() call to the init message
    error: str | None = None
    calls: list[str] = field(default_factory=list)


def _client() -> anthropic.Anthropic:
    workspace = os.environ.get("ANTHROPIC_WORKSPACE_ID")
    return anthropic.Anthropic(default_headers={"anthropic-workspace-id": workspace} if workspace else None)


def run_loop(task: Task, rep: int, client: anthropic.Anthropic, model: str) -> RunRecord:
    svc = LoopRx.with_sample_data()
    approver = lambda _n, _a: Decision(task.approval == "approve", f"automatic policy: {task.approval}")
    started = time.perf_counter()
    result = loop_run(client, svc, task.prompt, approver=approver, cfg=LoopConfig(model=model, server_tools=None))
    wall = time.perf_counter() - started
    calls = [c.name for t in result.turns for c in t.calls]
    executed = sum(1 for t in result.turns for c in t.calls
                   if c.name == "cancel_prescription" and c.approved and not c.is_error)
    out = Outcome(result.text, calls, executed, svc.prescriptions["RX-1003"]["status"])
    ok, note = task.check(out) if result.outcome == "completed" else (False, f"outcome {result.outcome}")
    u = result.usage()
    return RunRecord("loop", task.id, rep, ok, note, len(result.turns), len(calls),
                     u["input_tokens"] + u["cache_creation_input_tokens"] + u["cache_read_input_tokens"],
                     u["cache_read_input_tokens"], u["output_tokens"], round(result.cost_usd(model) or 0, 6),
                     round(wall, 2), calls=calls)


async def run_sdk(task: Task, rep: int, model: str) -> RunRecord:
    svc = SdkRx.with_sample_data()
    audit = AuditLog()

    async def approver(_n: str, _a: dict[str, Any]) -> bool:
        return task.approval == "approve"

    options = build_options(svc, approver, audit, model=model)
    started = time.perf_counter()
    startup = None
    result: ResultMessage | None = None
    async for message in query(prompt=prompt_stream(task.prompt), options=options):  # read to the end
        if isinstance(message, SystemMessage) and message.subtype == "init" and startup is None:
            startup = time.perf_counter() - started
        elif isinstance(message, ResultMessage):
            result = message
    wall = time.perf_counter() - started
    prefix = "mcp__rx__"
    calls = [e["tool"].removeprefix(prefix) for e in audit.events if e["event"] == "tool_requested"]
    executed = sum(1 for e in audit.events if e["event"] == "tool_completed"
                   and e["tool"] == prefix + "cancel_prescription" and not e["is_error"])
    if result is None:
        return RunRecord("sdk", task.id, rep, False, "no result message", 0, len(calls), 0, 0, 0, 0.0,
                         round(wall, 2), startup, calls=calls)
    out = Outcome(result.result or "", calls, executed, svc.prescriptions["RX-1003"]["status"])
    ok, note = task.check(out) if result.subtype == "success" else (False, f"result {result.subtype}")
    u = result.usage or {}
    return RunRecord("sdk", task.id, rep, ok, note, result.num_turns, len(calls),
                     int(u.get("input_tokens", 0)) + int(u.get("cache_creation_input_tokens", 0))
                     + int(u.get("cache_read_input_tokens", 0)),
                     int(u.get("cache_read_input_tokens", 0)), int(u.get("output_tokens", 0)),
                     round(result.total_cost_usd or 0, 6), round(wall, 2),
                     round(startup, 2) if startup is not None else None, calls=calls)


def summarise(records: list[RunRecord]) -> str:
    med = lambda xs: statistics.median(xs) if xs else 0
    lines = [f"{'task':<16}{'impl':<6}{'ok':>6}{'calls':>7}{'tools':>7}{'in_tok':>9}{'out':>6}"
             f"{'cost':>10}{'wall_s':>8}{'start_s':>9}"]
    for task in dict.fromkeys(r.task for r in records):
        for impl in ("loop", "sdk"):
            rs = [r for r in records if r.task == task and r.impl == impl]
            if not rs:
                continue
            starts = [r.startup_s for r in rs if r.startup_s is not None]
            lines.append(f"{task:<16}{impl:<6}{sum(r.ok for r in rs):>3}/{len(rs):<2}"
                         f"{med([r.model_calls for r in rs]):>7}{med([r.tool_calls for r in rs]):>7}"
                         f"{med([r.input_tokens for r in rs]):>9}{med([r.output_tokens for r in rs]):>6}"
                         f"{med([r.cost_usd for r in rs]):>10.4f}{med([r.wall_s for r in rs]):>8.1f}"
                         f"{(f'{med(starts):.1f}' if starts else '-'):>9}")
    for impl in ("loop", "sdk"):
        rs = [r for r in records if r.impl == impl]
        if rs:
            lines.append(f"TOTAL {impl:<4}  ok {sum(r.ok for r in rs)}/{len(rs)}  "
                         f"cost ${sum(r.cost_usd for r in rs):.4f}  median wall {med([r.wall_s for r in rs]):.1f}s")
    failures = [r for r in records if not r.ok]
    for r in failures:
        lines.append(f"FAILED {r.impl} {r.task} rep {r.rep}: {r.note or r.error}  calls={r.calls}")
    return "\n".join(lines)


async def main_async(a: argparse.Namespace) -> int:
    warnings.filterwarnings("ignore", category=CanUseToolShadowedWarning)  # intentional, see Part 2
    tasks = [t for t in TASKS if not a.tasks or t.id in a.tasks.split(",")]
    impls = [a.only] if a.only else ["loop", "sdk"]
    client = _client()
    records: list[RunRecord] = []
    with open(a.out, "a", encoding="utf-8") as fh:
        for rep in range(1, a.reps + 1):
            for task in tasks:
                for impl in impls:  # alternate so neither always runs on a warmer cache
                    try:
                        rec = (run_loop(task, rep, client, a.model) if impl == "loop"
                               else await run_sdk(task, rep, a.model))
                    except Exception as e:  # record and carry on; one bad run should not end the benchmark
                        rec = RunRecord(impl, task.id, rep, False, "exception", 0, 0, 0, 0, 0, 0.0, 0.0,
                                        error=f"{type(e).__name__}: {str(e)[:200]}")
                    records.append(rec)
                    fh.write(json.dumps(asdict(rec)) + "\n")
                    fh.flush()
                    print(f"{impl:<5} {task.id:<16} rep {rep}  ok={rec.ok}  ${rec.cost_usd:.4f}  {rec.wall_s:.1f}s"
                          + (f"  {rec.note or rec.error}" if not rec.ok else ""), flush=True)
                impls.reverse()
    print("\n" + summarise(records))
    return 0 if all(r.ok for r in records) else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="bench")
    p.add_argument("--reps", type=int, default=3)
    p.add_argument("--model", default="claude-opus-5-5")
    p.add_argument("--only", choices=["loop", "sdk"])
    p.add_argument("--tasks", help="comma-separated task ids")
    p.add_argument("--out", default="results.jsonl")
    return asyncio.run(main_async(p.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
