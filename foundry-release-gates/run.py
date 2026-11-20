"""Command line for the Foundry release gate.

  python run.py baseline                     create the vector store and agent version 1
  python run.py gate --version 1             simulate, judge, check and decide
  python run.py gate --version 3 --production 1
  python run.py estimate --version 1         optimizer cost estimate, no job created
  python run.py optimize --version 1         run the agent optimizer
  python run.py insights                     on-demand Agent Insights run over recent traces
  python run.py show --version 3             print a version's instructions
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict

from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential

from rxgate import foundry
from rxgate.decide import decide
from rxgate.gate import summarise
from rxgate.scenarios import write_seed_file


def _clients():
    credential = DefaultAzureCredential()
    project = AIProjectClient(endpoint=foundry.env("FOUNDRY_PROJECT_ENDPOINT"), credential=credential)
    return project, project.get_openai_client()


def cmd_baseline(_: argparse.Namespace) -> None:
    project, oai = _clients()
    store = foundry.ensure_vector_store(oai)
    version = foundry.create_agent_version(project, store, foundry.BASELINE_INSTRUCTIONS, "baseline")
    foundry.save_state(production_version=version)
    print(f"vector store {store}; agent {foundry.AGENT_NAME} version {version} (marked as production)")


def _load_gate(version: str):
    path = foundry.RESULTS / f"simulation-v{version}.json"
    if not path.exists():
        return None
    result, _ = summarise(version, json.loads(path.read_text())["items"])
    return result


def cmd_gate(args: argparse.Namespace) -> None:
    if args.reuse:
        saved = json.loads((foundry.RESULTS / f"simulation-v{args.version}.json").read_text())
        items, seconds = saved["items"], 0.0
    else:
        project, oai = _clients()
        seed = write_seed_file(foundry.RESULTS / "seed-scenarios.jsonl")
        run = foundry.simulate(project, oai, args.version, seed)
        items, seconds = run.items, run.seconds
        print(f"simulation {run.status} in {run.seconds:.0f}s, {len(run.items)} conversations")
    candidate, rows = summarise(args.version, items)
    production = _load_gate(args.production) if args.production else None
    decision = decide(candidate, production)

    print(f"\n{'scenario':<18} {'turns':>5} {'ms':>6}  " + "  ".join(f"{j[:10]:>10}" for j in foundry.JUDGES) + "  checks")
    for row in sorted(rows, key=lambda r: str(r["scenario"])):
        def mark(j):
            if j not in row["judges"]:
                return "-"
            m = "pass" if row["judges"][j] else "FAIL"
            return f"({m.lower()})" if j in row["excluded"] else m
        marks = "  ".join(f"{mark(j):>10}" for j in foundry.JUDGES)
        print(f"{str(row['scenario']):<18} {row['turns']:>5} {int(row['latency_ms'] or 0):>6}  {marks}  {'; '.join(row['failures']) or 'ok'}")
    print("\n(lower case in brackets) = judge not counted: the right answer in that scenario is a refusal")
    print("pass rates: " + ", ".join(f"{k}={v:.2f}" for k, v in candidate.pass_rates.items()))
    if production:
        print("production: " + ", ".join(f"{k}={v:.2f}" for k, v in production.pass_rates.items()))
    print(f"\nDECISION v{args.version}: {'READY FOR CLINICAL SAFETY SIGN-OFF' if decision.ready_for_signoff else 'BLOCKED'}")
    for line in decision.reasons + decision.warnings:
        print(f"  {line}")
    foundry.dump(
        f"gate-v{args.version}.json",
        {"rows": rows, "pass_rates": candidate.pass_rates, "decision": asdict(decision), "seconds": seconds},
    )
    sys.exit(0 if decision.ready_for_signoff else 2)


def cmd_estimate(args: argparse.Namespace) -> None:
    project, _ = _clients()
    est = foundry.estimate_optimization(project, args.version, args.max_candidates)
    print(json.dumps(foundry._plain(est), indent=2))


def cmd_optimize(args: argparse.Namespace) -> None:
    project, _ = _clients()
    job_id, result, candidates = foundry.optimize(project, args.version, args.max_candidates)
    summary = result.candidate_summary
    print(f"job {job_id}: termination={result.termination_reason}")
    if summary:
        print(f"baseline {summary.baseline_id} score={summary.baseline_score}; best {summary.best_id} score={summary.best_score}")
    for c in candidates:
        score = c.evaluation.score if c.evaluation else None
        print(f"  {c.name:<24} status={c.status} score={score} agent_version={c.agent_version}")
    for usage in result.token_usage or []:
        print(f"  tokens: {foundry._plain(usage)}")


def cmd_insights(args: argparse.Namespace) -> None:
    project, _ = _clients()
    out = foundry.run_insights(project, args.lookback_hours)
    run = out["run"]
    print(f"traces in window={run.get('traces_in_window')} analysed={run.get('traces_analyzed')} insights={run.get('insights_created')}")
    for i in out["insights"]:
        print(f"- [{i.get('severity')}] {i.get('title')} (traces={i.get('trace_count')})")


def cmd_show(args: argparse.Namespace) -> None:
    project, _ = _clients()
    print(foundry.get_instructions(project, args.version))


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(required=True)
    sub.add_parser("baseline").set_defaults(fn=cmd_baseline)
    g = sub.add_parser("gate")
    g.add_argument("--version", required=True)
    g.add_argument("--production")
    g.add_argument("--reuse", action="store_true", help="re-score the saved simulation instead of running a new one")
    g.set_defaults(fn=cmd_gate)
    for name, fn in (("estimate", cmd_estimate), ("optimize", cmd_optimize)):
        p = sub.add_parser(name)
        p.add_argument("--version", required=True)
        p.add_argument("--max-candidates", type=int, default=2)
        p.set_defaults(fn=fn)
    i = sub.add_parser("insights")
    i.add_argument("--lookback-hours", type=int, default=6)
    i.set_defaults(fn=cmd_insights)
    s = sub.add_parser("show")
    s.add_argument("--version", required=True)
    s.set_defaults(fn=cmd_show)
    args = parser.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
