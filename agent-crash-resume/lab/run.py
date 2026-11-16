"""Kill each agent in the middle of its work, recover it, and count what happened twice.

    python lab/run.py <output directory> --langgraph <python> --agent-framework <python> --adk <python>

Each framework runs in its own virtual environment, so each is given its own interpreter. For every
case the lab starts a fresh model stand-in and a fresh state directory, runs the agent until a tool
reaches the chosen crash point, sends SIGKILL to the agent process, and then runs the recovery action
in a new process. The ledger written by the tools says what was really done.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
FRAMEWORKS = {  # name: (script, recovery actions it supports)
    "LangGraph": ("langgraph_agent.py", ["resume", "resend"]),
    "Agent Framework": ("agent_framework_agent.py", ["resend"]),
    "ADK": ("adk_agent.py", ["resume", "resend"]),
}
CRASHES = {
    "charge_card:before": "during charge_card, before the charge",
    "charge_card:after": "during charge_card, after the charge",
    "send_confirmation:before": "after charge_card returned, before the email",
}
TOOLS = ("reserve_stock", "charge_card", "send_confirmation")


def wait_for(path: Path, seconds: float) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if path.exists():
            return True
        time.sleep(0.05)
    return False


def last_line(text: str) -> str:
    """The line of a traceback that names the error, or failing that the last thing printed."""
    lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
    errors = [line for line in lines if "Error" in line.split(":")[0] or "Exception" in line.split(":")[0]]
    chosen = errors[-1] if errors else (lines[-1] if lines else "")
    return " ".join(chosen.split())[:170]


def one_case(python: str, script: str, crash: str | None, action: str | None, tools: str) -> dict:
    with tempfile.TemporaryDirectory() as directory:
        work = Path(directory)
        stand_in = subprocess.Popen([sys.executable, str(HERE / "standin.py"), str(work / "port"), str(work / "requests.jsonl")])
        try:
            if not wait_for(work / "port", 10):
                raise RuntimeError("the stand-in did not start")
            url = f"http://127.0.0.1:{(work / 'port').read_text()}"
            env = {**os.environ, "LAB_LEDGER": str(work / "ledger.jsonl"), "LAB_MARKER": str(work / "crash.marker"), "LAB_TOOLS": tools,
                   "PYTHONWARNINGS": "ignore"}
            command = [python, str(HERE / "agents" / script)]
            first = subprocess.Popen(command + ["start", str(work), url], env={**env, "CRASH_AT": crash or ""}, cwd=work,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
            row: dict = {"crash": crash, "recovery": action, "tools": tools}
            if crash is None:
                out, err = first.communicate(timeout=90)
                row.update(finished=first.returncode == 0, said=last_line(out) or last_line(err))
            else:
                if not wait_for(work / "crash.marker", 60):
                    first.kill()
                    raise RuntimeError("the agent never reached the crash point: " + last_line(first.communicate()[1]))
                os.killpg(first.pid, signal.SIGKILL)  # no handlers, no flush, no goodbye: the process is gone
                first.wait()
                before = len((work / "requests.jsonl").read_text().splitlines())
                second = subprocess.run(command + [action, str(work), url], env=env, cwd=work, capture_output=True, text=True, timeout=90)
                seen = [json.loads(line) for line in (work / "requests.jsonl").read_text().splitlines()[before:]]
                row.update(finished=second.returncode == 0 and "Order O-1001 is placed" in second.stdout,
                           said=last_line(second.stdout) if second.returncode == 0 else last_line(second.stderr),
                           model_requests_after_crash=len(seen), first_request_after_crash=seen[0] if seen else None,
                           rejected_by_model_api=sum(1 for r in seen if r["answer"] == "HTTP 400"))
            entries = [json.loads(line) for line in (work / "ledger.jsonl").read_text().splitlines()] if (work / "ledger.jsonl").exists() else []
            row["effects"] = {tool: sum(1 for e in entries if e["kind"] == "effect" and e["tool"] == tool) for tool in TOOLS}
            row["replayed"] = {tool: sum(1 for e in entries if e["kind"] == "replayed" and e["tool"] == tool) for tool in TOOLS}
            return row
        finally:
            stand_in.kill()
            stand_in.wait()


def verdict(row: dict) -> str:
    effects = row["effects"]
    if not row["finished"]:
        return "did not finish"
    if all(count == 1 for count in effects.values()):
        return "exactly once"
    return "DUPLICATED: " + ", ".join(f"{tool} x{count}" for tool, count in effects.items() if count > 1)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("out")
    parser.add_argument("--langgraph", required=True)
    parser.add_argument("--agent-framework", required=True)
    parser.add_argument("--adk", required=True)
    options = parser.parse_args()
    pythons = {"LangGraph": options.langgraph, "Agent Framework": options.agent_framework, "ADK": options.adk}
    rows = []
    print(f"{'framework':<16} {'crash point':<46} {'recovery':<8} {'tools':<10} {'effects r/c/s':<13} outcome")
    for name, (script, actions) in FRAMEWORKS.items():
        baseline = one_case(pythons[name], script, None, None, "plain")
        rows.append({"framework": name, **baseline})
        counts = "/".join(str(baseline["effects"][tool]) for tool in TOOLS)
        print(f"{name:<16} {'none':<46} {'-':<8} {'plain':<10} {counts:<13} {verdict(baseline)}")
        for crash, described in CRASHES.items():
            for action in actions:
                for tools in ("plain", "idempotent"):
                    try:
                        row = one_case(pythons[name], script, crash, action, tools)
                    except Exception as error:  # noqa: BLE001  one broken case must not hide the others
                        row = {"crash": crash, "recovery": action, "tools": tools, "finished": False, "said": f"lab error: {error}",
                               "effects": dict.fromkeys(TOOLS, 0), "replayed": dict.fromkeys(TOOLS, 0)}
                    rows.append({"framework": name, **row})
                    counts = "/".join(str(row["effects"][tool]) for tool in TOOLS)
                    note = verdict(row) + ("" if row["finished"] else f" ({row['said']})")
                    print(f"{name:<16} {described:<46} {action:<8} {tools:<10} {counts:<13} {note[:150]}")
    os.makedirs(options.out, exist_ok=True)
    with open(os.path.join(options.out, "crash-resume.json"), "w", encoding="utf-8") as handle:
        json.dump(rows, handle, indent=2)
    crashed = [r for r in rows if r["crash"]]
    for tools in ("plain", "idempotent"):
        subset = [r for r in crashed if r["tools"] == tools]
        print(f"\n{tools} tools: {sum(verdict(r) == 'exactly once' for r in subset)} of {len(subset)} recoveries ended with every effect exactly once, "
              f"{sum(verdict(r).startswith('DUPLICATED') for r in subset)} duplicated an effect, {sum(not r['finished'] for r in subset)} did not finish")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
