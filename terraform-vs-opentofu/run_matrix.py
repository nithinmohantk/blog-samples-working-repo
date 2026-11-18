"""Run every experiment on both tools and record what each one did.

    python run_matrix.py <terraform binary> <tofu binary> <output directory>

Each experiment is a small configuration. A tool refusing it is a result, not an error. The run fails
only when a result differs from experiments.json, which is how a release that changes behaviour shows up.
"""
from __future__ import annotations

import json
import os
import pathlib
import shlex
import shutil
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
DEFAULT_STEPS = ["init -input=false", "validate", "apply -input=false -auto-approve"]


def first_error(output: str) -> str:
    lines = output.splitlines()
    for index, line in enumerate(lines):
        if (line.startswith("Error:") or line.startswith("│ Error:")) and "encountered problems during initialisation" not in line:
            rest = [l.strip("│ ").strip() for l in lines[index + 1:index + 12]]
            detail = " ".join(l for l in rest if l and not l.startswith("on ") and not l[:1].isdigit() and not l.startswith("with "))
            return (line.strip("│ ").strip() + " | " + detail)[:300]
    return (lines[-1] if lines else "")[:300]


def run(tool: str, other: str, experiment: dict) -> dict:
    work = pathlib.Path(tempfile.mkdtemp())
    shutil.copytree(HERE / "experiments" / experiment["id"], work, dirs_exist_ok=True)
    env = {**os.environ, "TF_IN_AUTOMATION": "1", "TF_CLI_ARGS": "-no-color", "CHECKPOINT_DISABLE": "1", **experiment.get("env", {})}
    for step in experiment.get("steps", DEFAULT_STEPS):
        # A step written as "other:<command>" runs with the other tool, in the same directory.
        binary, command = (other, step[len("other:"):]) if step.startswith("other:") else (tool, step)
        if binary is other:
            shutil.rmtree(work / ".terraform", ignore_errors=True)
        done = subprocess.run([binary, *shlex.split(command)], cwd=work, env=env, capture_output=True, text=True)
        if done.returncode != 0:
            stage = ("the other tool's " if binary is other else "") + command.split()[0]
            return {"result": "fail", "stage": stage, "detail": first_error(done.stdout + done.stderr)}
    note = ""
    if (work / "check.py").exists():
        check = subprocess.run([sys.executable, "check.py", tool], cwd=work, env=env, capture_output=True, text=True)
        note = check.stdout.strip()
        if check.returncode != 0:
            return {"result": "fail", "stage": "check", "detail": note}
    return {"result": "pass", "stage": "", "detail": note}


def main() -> int:
    tools = {"terraform": sys.argv[1], "tofu": sys.argv[2]}
    out = pathlib.Path(sys.argv[3])
    out.mkdir(parents=True, exist_ok=True)
    experiments = json.loads((HERE / "experiments.json").read_text(encoding="utf-8"))
    rows, unexpected = [], 0
    for experiment in experiments:
        row = {"id": experiment["id"], "title": experiment["title"]}
        for name, binary in tools.items():
            row[name] = run(binary, next(b for n, b in tools.items() if n != name), experiment)
            row[name]["expected"] = experiment["expect"][name]
            if row[name]["result"] != experiment["expect"][name]:
                unexpected += 1
        rows.append(row)
        print(f"{row['id']:<40} terraform={row['terraform']['result']:<5} tofu={row['tofu']['result']:<5}"
              + ("   UNEXPECTED" if any(row[t]["result"] != row[t]["expected"] for t in tools) else ""))
    (out / "matrix.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    lines = ["| Experiment | Terraform | OpenTofu |", "| --- | --- | --- |"]
    for row in rows:
        cells = [f"{row[t]['result']}" + (f" at {row[t]['stage']}" if row[t]["stage"] else "") for t in tools]
        lines.append(f"| {row['title']} | {cells[0]} | {cells[1]} |")
    (out / "matrix.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n{len(rows)} experiments, {unexpected} unexpected result(s)")
    return 1 if unexpected else 0


if __name__ == "__main__":
    sys.exit(main())
