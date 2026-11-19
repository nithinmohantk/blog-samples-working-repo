"""Running code the model wrote, somewhere other than the agent's own process."""
from __future__ import annotations

import os
import resource
import subprocess
import sys
import tempfile


def _limits(memory_mb: int, cpu_s: int):
    def apply() -> None:
        os.setsid()
        resource.setrlimit(resource.RLIMIT_AS, (memory_mb * 1024 * 1024, memory_mb * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_s, cpu_s))
        resource.setrlimit(resource.RLIMIT_FSIZE, (16 * 1024 * 1024, 16 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

    return apply


def run_python(code: str, *, timeout_s: float = 5.0, memory_mb: int = 256, mode: str | None = None) -> str:
    """Run a snippet and return what it printed.

    ``process``: a child process with an empty environment, a scratch directory, and limits on memory,
    CPU time and file size. It keeps the agent alive and keeps the agent's secrets out. It is not a
    security boundary: the child has the same user, the same files and the same network.

    ``docker``: the same snippet in a container with no network, a read-only root and its own limits.
    """
    mode = mode or os.environ.get("HARNESS_SANDBOX", "process")
    with tempfile.TemporaryDirectory(prefix="harness-") as scratch:
        if mode == "docker":
            command = [
                "docker", "run", "--rm", "--network", "none", "--read-only", "--tmpfs", "/tmp:size=16m",
                "--memory", f"{memory_mb}m", "--memory-swap", f"{memory_mb}m", "--cpus", "1", "--pids-limit", "64",
                "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--user", "65534:65534",
                os.environ.get("HARNESS_SANDBOX_IMAGE", "python:3.13-slim"), "python", "-I", "-c", code,
            ]
            run = subprocess.run(command, capture_output=True, text=True, timeout=timeout_s + 20, check=False)
        else:
            run = subprocess.run(
                [sys.executable, "-I", "-c", code],
                capture_output=True, text=True, timeout=timeout_s, check=False,
                cwd=scratch, env={"PATH": "/usr/bin:/bin", "HOME": scratch}, preexec_fn=_limits(memory_mb, int(timeout_s) + 1),
            )
    if run.returncode != 0:
        reason = (run.stderr.strip().splitlines() or [f"exit {run.returncode}"])[-1]
        raise RuntimeError(f"snippet failed: {reason[:300]}")
    return run.stdout
