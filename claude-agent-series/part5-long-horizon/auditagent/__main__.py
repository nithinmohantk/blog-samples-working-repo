"""Run the long-horizon audit from a terminal and score it against the answer key.

    python -m auditagent --model claude-fable-5-2                    # full run
    python -m auditagent --model claude-fable-5-2 --stop-after 6     # stop after 6 turns (simulated interruption)
    python -m auditagent --resume                                    # continue from the checkpoint

ANTHROPIC_API_KEY (and ANTHROPIC_WORKSPACE_ID for a multi-workspace key) come from the
environment and are never printed. All data is synthetic.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

import anthropic

from .data import RULES, expected_findings
from .loop import LongRunConfig, RunState, run
from .service import AuditService


def score(svc: AuditService) -> dict:
    expected = expected_findings(svc.prescriptions, svc.dispenses)
    got = set(svc.findings)
    out = {}
    for rule in (*RULES, "ALL"):
        e = {f for f in expected if rule == "ALL" or f[1] == rule}
        g = {f for f in got if rule == "ALL" or f[1] == rule}
        tp = len(e & g)
        out[rule] = {"expected": len(e), "recorded": len(g), "correct": tp,
                     "precision": round(tp / len(g), 3) if g else None, "recall": round(tp / len(e), 3) if e else None}
    out["missed"] = sorted(map(list, expected - got))
    out["extra"] = sorted(map(list, got - expected))
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="auditagent")
    p.add_argument("--model", default="claude-fable-5-2", choices=["claude-fable-5-2", "claude-opus-5-5"])
    p.add_argument("--effort", default="high", choices=["low", "medium", "high", "xhigh", "max"])
    p.add_argument("--budget", type=float, default=4.0, help="stop when the run has cost this many USD")
    p.add_argument("--compact-at", type=int, default=40_000, help="compact when the context passes this many tokens")
    p.add_argument("--checkpoint", default="state.json")
    p.add_argument("--resume", action="store_true")
    p.add_argument("--stop-after", type=int, help="stop after this many turns in this session")
    p.add_argument("--results", default=None, help="write the run summary and score to this JSON file")
    p.add_argument("--log", action="store_true")
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO if a.log else logging.WARNING, stream=sys.stderr, format="%(message)s")

    svc = AuditService.with_sample_data()
    path = Path(a.checkpoint)
    state, model = None, a.model
    if a.resume:
        state, model = RunState.load(path, svc)
        print(f"resuming {model} from turn {state.turns}: {svc.progress()['reviewed']} reviewed, "
              f"{len(svc.findings)} findings, ${state.usage.cost(model):.4f} so far")
    cfg = LongRunConfig(model=model, effort=a.effort, budget_usd=a.budget, compact_at_tokens=a.compact_at,
                        stop_after_turns=a.stop_after)

    workspace = os.environ.get("ANTHROPIC_WORKSPACE_ID")
    client = anthropic.Anthropic(default_headers={"anthropic-workspace-id": workspace} if workspace else None)
    try:
        result = run(client, svc, cfg, path, state)
    except anthropic.APIStatusError as e:
        print(f"API error {e.status_code} ({type(e).__name__}), request_id={e.request_id}: {e.message}", file=sys.stderr)
        print("The last completed turn is in the checkpoint; fix the cause and run with --resume.", file=sys.stderr)
        return 2

    st = result.state
    for ev in st.events:
        if ev["event"] == "turn":
            tools = ",".join(sorted(set(ev["tools"]))) or "-"
            print(f"turn {ev['turn']:>3} {ev['stop_reason']:<9} ctx={ev['context']:>6} ${ev['cost']:<7} {tools}"
                  + (f"  | {ev['text'][:70]}" if ev["text"] else ""))
        else:
            print(f"      {json.dumps(ev)}")
    u = st.usage
    prog = svc.progress()
    print(f"\noutcome={result.outcome} model={model} effort={cfg.effort} turns={st.turns} tool_calls={st.tool_calls} "
          f"compactions={st.compactions} elapsed={st.elapsed_s:.0f}s")
    print(f"input={u.input} cache_write={u.cache_write} cache_read={u.cache_read} output={u.output} "
          f"cost=${u.cost(model):.4f}  reviewed={prog['reviewed']}/{prog['total']}")
    sc = score(svc)
    for rule in (*RULES, "ALL"):
        r = sc[rule]
        print(f"  {rule:<16} expected={r['expected']:>2} recorded={r['recorded']:>2} correct={r['correct']:>2} "
              f"precision={r['precision']} recall={r['recall']}")
    print(f"  missed={sc['missed']}\n  extra={sc['extra']}")
    if result.text:
        print("\n" + result.text)
    if a.results:
        Path(a.results).write_text(json.dumps({"outcome": result.outcome, "model": model, "effort": cfg.effort,
                                               "turns": st.turns, "tool_calls": st.tool_calls,
                                               "compactions": st.compactions, "elapsed_s": round(st.elapsed_s, 1),
                                               "usage": u.__dict__, "cost_usd": round(u.cost(model), 4),
                                               "score": sc, "events": st.events}, indent=1))
    return 0 if result.outcome in ("completed", "stopped") else 1


if __name__ == "__main__":
    sys.exit(main())
