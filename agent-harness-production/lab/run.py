"""Run every scenario on the bare loop and on the harness, each in its own process, and compare.

Usage: python -m lab.run <output directory> [--docker]
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from lab.scenarios import scenarios


def probe_listener() -> tuple[str, int]:
    """Something on this machine's own address that code should not be able to reach."""
    host = "127.0.0.1"
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as finder:
        try:
            finder.connect(("192.0.2.1", 9))   # no packet is sent; this only asks which address would be used
            host = finder.getsockname()[0]
        except OSError:
            pass
    server = socket.create_server(("0.0.0.0", 0))
    threading.Thread(target=lambda: [server.accept()[0].close() for _ in iter(int, 1)], daemon=True).start()
    return host, server.getsockname()[1]


def once(name: str, mode: str, work: Path, probe: tuple[str, int], env: dict[str, str]) -> dict:
    run = subprocess.run([sys.executable, "-m", "lab.one", name, mode, str(work), probe[0], str(probe[1])],
                         capture_output=True, text=True, timeout=120, env={**os.environ, **env}, check=False)
    lines = [line for line in run.stdout.splitlines() if line.startswith("{")]
    return json.loads(lines[-1]) if lines else {"ended": f"process died (exit {run.returncode})", "refunds": None}


def outcome(name: str, mode: str, probe: tuple[str, int], sandbox: str) -> dict:
    scenario = scenarios(probe)[name]
    with tempfile.TemporaryDirectory(prefix=f"lab-{name}-") as folder:
        work = Path(folder)
        env = {"HARNESS_SANDBOX": sandbox, "LAB_CRASH_AFTER_WRITE": "1" if scenario.crash_once else "0"}
        result = once(name, mode, work, probe, env)
        if scenario.crash_once:
            first = result["ended"]
            result = once(name, mode, work, probe, env)   # the same command again, as a supervisor would
            result["first_attempt"] = first
        return result


def describe(name: str, r: dict) -> str:
    """One line a reader can check against the JSON."""
    refunds = ", ".join(f"{o} {a:.2f}" for o, a in (r.get("refunds") or [])) or "none"
    extra = {
        "runaway": f"{r.get('model_calls')} model calls",
        "huge_output": f"largest request {r.get('largest_request_chars', 0):,} characters",
        "slow_tool": f"{r.get('seconds')} s",
        "injected_write": f"refunds: {refunds}",
        "secret_in_env": "key in the answer" if r.get("leaked_key") else "no key in the answer",
        "memory_bomb": " ".join((r.get("answer") or "").split())[:90],
        "network": " ".join((r.get("answer") or "").split())[:90],
        "crash_after_write": f"first attempt: {r.get('first_attempt')}; refunds: {refunds}",
        "flaky_tool": (r.get("answer") or "")[:60],
    }.get(name, (r.get("answer") or "")[:60])
    return f"{r['ended']}; {extra}".rstrip("; ")


def main(out: Path, docker: bool) -> int:
    probe = probe_listener()
    names = list(scenarios(probe))
    results: dict[str, dict[str, dict]] = {}
    lines = []
    for name in names:
        title = scenarios(probe)[name].title
        results[name] = {"bare": outcome(name, "bare", probe, "process"), "hardened": outcome(name, "hardened", probe, "process")}
        lines += [f"{name}: {title}", f"  bare      {describe(name, results[name]['bare'])}", f"  harness   {describe(name, results[name]['hardened'])}"]
        if docker and scenarios(probe)[name].code_tool:
            results[name]["docker"] = outcome(name, "hardened", probe, "docker")
            lines.append(f"  container {describe(name, results[name]['docker'])}")
    (out / "outcomes.txt").write_text("\n".join(lines) + "\n")
    (out / "outcomes.json").write_text(json.dumps(results, indent=1))
    print("\n".join(lines))

    for name in ("flaky_tool", "injected_write", "crash_after_write"):
        spans = results[name]["hardened"]["spans"]
        (out / f"trace-{name}.txt").write_text("".join(
            f"{span[0]:<28} {'error.type=' + span[1] if span[1] else 'ok':<26}{' retries=' + str(span[2]) if span[2] else ''}{' replayed' if span[3] else ''}\n" for span in spans))

    # What the article claims, checked. A change in behaviour fails the build.
    b = {n: results[n]["bare"] for n in names}
    h = {n: results[n]["hardened"] for n in names}
    checks = {
        "bare: runaway never ends by itself": b["runaway"]["ended"].startswith("still looping"),
        "harness: runaway stopped by the model call budget": h["runaway"]["ended"] == "stopped: model calls (12)",
        "bare: bad arguments crash the run": b["bad_arguments"]["ended"] == "crashed: TypeError",
        "harness: bad arguments are corrected": h["bad_arguments"]["ended"] == "answered" and "shipped" in h["bad_arguments"]["answer"],
        "bare: unknown tool crashes the run": b["unknown_tool"]["ended"] == "crashed: KeyError",
        "harness: unknown tool is reported and the run recovers": h["unknown_tool"]["ended"] == "answered",
        "bare: a transient failure crashes the run": b["flaky_tool"]["ended"] == "crashed: TransientError",
        "harness: a transient failure is retried": "attempt 3" in h["flaky_tool"]["answer"],
        "bare: 2 MB goes to the model": b["huge_output"]["largest_request_chars"] > 2_000_000,
        "harness: the result is cut to the limit": h["huge_output"]["largest_request_chars"] < 5_000,
        "bare: waits for the slow tool": b["slow_tool"]["seconds"] >= 6,
        "harness: gives up on the slow tool after 1 s": h["slow_tool"]["seconds"] < 3 and "did not answer" in h["slow_tool"]["answer"],
        "bare: the injected refund is paid": b["injected_write"]["refunds"] == [["O-1001", 500.0]],
        "harness: the injected refund is not paid": h["injected_write"]["refunds"] == [],
        "bare: the key leaks": b["secret_in_env"]["leaked_key"],
        "harness: the key does not leak": not h["secret_in_env"]["leaked_key"],
        "bare: 1 GB is allocated in the agent": "allocated 1073741824" in b["memory_bomb"]["answer"],
        "harness: the allocation fails in the child": "MemoryError" in h["memory_bomb"]["answer"],
        "bare: code reaches the network": "connected" in b["network"]["answer"],
        "harness, process sandbox: code still reaches the network": "connected" in h["network"]["answer"],
        "bare: crash and restart pays twice": len(b["crash_after_write"]["refunds"]) == 2,
        "harness: crash and restart pays once": len(h["crash_after_write"]["refunds"]) == 1 and h["crash_after_write"]["ended"] == "answered",
    }
    if docker:
        d = {n: results[n]["docker"] for n in names if "docker" in results[n]}
        checks |= {
            "container: code cannot reach the network": "connected" not in d["network"]["answer"] and d["network"]["ended"] == "answered",
            "container: the key does not leak": not d["secret_in_env"]["leaked_key"],
            "container: the allocation fails": "allocated" not in d["memory_bomb"]["answer"],
        }
    failed = [name for name, ok in checks.items() if not ok]
    summary = [f"{'ok  ' if ok else 'FAIL'} {name}" for name, ok in checks.items()] + [f"{len(checks) - len(failed)} of {len(checks)} checks passed"]
    (out / "checks.txt").write_text("\n".join(summary) + "\n")
    print("\n".join(summary))
    return 1 if failed else 0


if __name__ == "__main__":
    target = Path(sys.argv[1])
    target.mkdir(parents=True, exist_ok=True)
    sys.exit(main(target, "--docker" in sys.argv))
