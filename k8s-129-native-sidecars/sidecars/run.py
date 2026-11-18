"""Run each sidecar scenario against the current kubectl context and record what happened.

    python sidecars/run.py --label v1.29.2 --node kind-control-plane --out results.json
    python sidecars/run.py --label v1.28.7 --node old-control-plane --only native-on-old --out results.json

Each scenario applies one manifest from manifests/, waits, reads pod status
(and, for the shutdown scenarios, the event log the containers write on the
node), then deletes what it created.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyse import containers, last_terminated, parse_events, parse_stream, relative, seconds_between  # noqa: E402

MANIFESTS = Path(__file__).resolve().parents[1] / "manifests"


def kubectl(*args: str, check: bool = True, timeout: int = 180) -> str:
    done = subprocess.run(["kubectl", *args], capture_output=True, text=True, timeout=timeout)
    if check and done.returncode != 0:
        raise RuntimeError(f"kubectl {' '.join(args)}: {done.stderr.strip()}")
    return done.stdout + (done.stderr if not check else "")


def pod_of(selector: str) -> dict:
    items = json.loads(kubectl("get", "pods", "-l", selector, "-o", "json"))["items"]
    return items[0]


def wait_for(predicate, timeout: float, interval: float = 1.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    return None


def job_condition(name: str) -> str | None:
    job = json.loads(kubectl("get", "job", name, "-o", "json"))
    for cond in job.get("status", {}).get("conditions", []) or []:
        if cond["status"] == "True" and cond["type"] in ("Complete", "Failed"):
            return cond["type"]
    return None


def node_log(node: str, pod: str) -> str:
    return subprocess.run(["docker", "exec", node, "cat", f"/tmp/sidecar-events/{pod}/log"],
                          capture_output=True, text=True).stdout


def job_scenario(manifest: str, job: str, wait: int) -> dict:
    kubectl("apply", "-f", str(MANIFESTS / manifest))
    started = time.monotonic()
    outcome = wait_for(lambda: job_condition(job), wait)
    pod = pod_of(f"job-name={job}")
    result = {"job_condition": outcome or f"none after {wait} s",
              "seconds_to_condition": round(time.monotonic() - started, 1) if outcome else None,
              "pod_phase": pod["status"].get("phase"), "containers": containers(pod)}
    kubectl("delete", "job", job, "--wait=true", "--cascade=foreground")
    return result


def startup_order() -> dict:
    kubectl("apply", "-f", str(MANIFESTS / "pod-startup-order.yaml"))
    kubectl("wait", "--for=condition=Ready", "pod/startup-order", "--timeout=120s")
    pod = json.loads(kubectl("get", "pod", "startup-order", "-o", "json"))
    c = containers(pod)
    result = {"containers": c,
              "main_started_after_proxy_s": seconds_between(c["proxy"]["started"], c["main"]["started"])}
    kubectl("delete", "pod", "startup-order", "--grace-period=1", "--wait=true")
    return result


def shutdown(manifest: str, pod: str, node: str, origin: tuple[str, str]) -> dict:
    subprocess.run(["docker", "exec", node, "rm", "-rf", f"/tmp/sidecar-events/{pod}"], check=False)
    kubectl("apply", "-f", str(MANIFESTS / manifest))
    kubectl("wait", "--for=condition=Ready", f"pod/{pod}", "--timeout=120s")
    time.sleep(2)
    watch = subprocess.Popen(["kubectl", "get", "pod", pod, "-o", "json", "--watch"],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    time.sleep(1)
    started = time.monotonic()
    kubectl("delete", "pod", pod, "--wait=true", timeout=120)
    deleted_after = round(time.monotonic() - started, 1)
    watch.terminate()
    snapshots = parse_stream(watch.communicate()[0])
    events = parse_events(node_log(node, pod))
    return {"delete_returned_after_s": deleted_after,
            "events": relative([e for e in events if e[2] != "start"], origin),
            "final_states": {k: {"exit_code": v["exit_code"], "reason": v["reason"]}
                             for k, v in last_terminated(snapshots).items()}}


def native_on_old_cluster() -> dict:
    """Apply the native sidecar Job where the feature gate is off and see what the API keeps."""
    kubectl("apply", "-f", str(MANIFESTS / "job-native-sidecar.yaml"))
    stored = json.loads(kubectl("get", "job", "native-sidecar", "-o", "json"))
    init = stored["spec"]["template"]["spec"]["initContainers"][0]
    time.sleep(45)
    pod = pod_of("job-name=native-sidecar")
    result = {"stored_restartPolicy": init.get("restartPolicy", "(field dropped)"),
              "job_condition_after_45s": job_condition("native-sidecar"),
              "pod_phase": pod["status"].get("phase"), "containers": containers(pod)}
    kubectl("delete", "job", "native-sidecar", "--wait=true", "--cascade=foreground")
    return result


SCENARIOS = {
    "job-classic": lambda node: job_scenario("job-classic-sidecar.yaml", "classic-sidecar", 60),
    "job-native": lambda node: job_scenario("job-native-sidecar.yaml", "native-sidecar", 120),
    "startup-order": lambda node: startup_order(),
    "termination-order": lambda node: shutdown("pod-termination-order.yaml", "termination-order", node, ("main", "TERM")),
    "grace-squeeze": lambda node: shutdown("pod-grace-squeeze.yaml", "grace-squeeze", node, ("main", "TERM-ignored")),
    "sidecar-crash": lambda node: job_scenario("job-sidecar-crash.yaml", "sidecar-crash", 120),
    "native-on-old": lambda node: native_on_old_cluster(),
}


def main(argv: list[str] | None = None) -> dict:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True)
    parser.add_argument("--node", required=True, help="kind node container name, for the event logs")
    parser.add_argument("--only", nargs="*", choices=list(SCENARIOS))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    server = json.loads(kubectl("version", "-o", "json"))["serverVersion"]["gitVersion"]
    results = json.loads(args.out.read_text()) if args.out.exists() else {}
    for name in args.only or [n for n in SCENARIOS if n != "native-on-old"]:
        try:
            outcome = SCENARIOS[name](args.node)
        except Exception as err:  # record and carry on, so one failure does not hide the rest
            outcome = {"error": str(err)}
        results[f"{args.label}/{name}"] = {"server": server, **outcome}
        print(json.dumps({f"{args.label}/{name}": results[f"{args.label}/{name}"]}, indent=2), flush=True)
    args.out.write_text(json.dumps(results, indent=2))
    return results


if __name__ == "__main__":
    main()
