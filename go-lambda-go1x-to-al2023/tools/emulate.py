"""Runs each build in an AWS Lambda base image under the Runtime Interface Emulator and invokes it.

    python emulate.py <dist dir> <go1.x image> <provided.al2023 image> <output dir>

The go1.x image runs the executable named by the handler from /var/task. The provided.al2023 image starts
/var/runtime/bootstrap, so packages for it are mounted there (in a real zip deployment Lambda unpacks the package
to /var/task and runs /var/task/bootstrap; the image looks in /var/runtime instead). Standard library only.
"""
import json
import pathlib
import subprocess
import sys
import time
import urllib.error
import urllib.request

dist, go_image, al2023_image, out = (pathlib.Path(sys.argv[1]).resolve(), sys.argv[2], sys.argv[3],
                                     pathlib.Path(sys.argv[4]).resolve())
here = pathlib.Path(__file__).resolve().parent.parent
EVENTS = {p.stem: p.read_bytes() for p in sorted((here / "events").glob("*.json"))}
PORT, NAME = 9100, "go-lambda-emulated"
URL = f"http://127.0.0.1:{PORT}/2015-03-31/functions/function/invocations"

# label, build folder, image, platform, mount point, handler argument, expected to work
SCENARIOS = [
    ("go1.x image, go1.x build", "go1x", go_image, "linux/amd64", "/var/task", "main", True),
    ("provided.al2023, norpc build, x86_64", "al2023-amd64", al2023_image, "linux/amd64", "/var/runtime", "bootstrap", True),
    ("provided.al2023, norpc build, arm64 (QEMU)", "al2023-arm64", al2023_image, "linux/arm64", "/var/runtime", "bootstrap", True),
    ("provided.al2023, go1.x build renamed bootstrap", "rpc-bootstrap", al2023_image, "linux/amd64", "/var/runtime", "bootstrap", True),
    ("provided.al2023, go1.x package unchanged", "go1x", al2023_image, "linux/amd64", "/var/runtime", "main", False),
    ("provided.al2023, cgo build from the CI runner", "cgo-bootstrap", al2023_image, "linux/amd64", "/var/runtime", "bootstrap", None),
    ("go1.x image, cgo build from the CI runner", "cgo-main", go_image, "linux/amd64", "/var/task", "main", None),
    ("go1.x image, norpc build", "norpc-main", go_image, "linux/amd64", "/var/task", "main", None),
]


def docker(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], capture_output=True, text=True)


def invoke(event: bytes) -> tuple[int, dict | str]:
    request = urllib.request.Request(URL, data=event, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read().decode()
            status = response.status
    except urllib.error.HTTPError as err:
        raw, status = err.read().decode(), err.code
    try:
        return status, json.loads(raw)
    except json.JSONDecodeError:
        return status, raw


def wait_ready(seconds: float = 60) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/", timeout=2)
            return True
        except urllib.error.HTTPError:
            return True            # the emulator answers 404 on /, which means it is listening
        except OSError:
            time.sleep(0.5)
    return False


def run(label, folder, image, platform, mount, handler, expected):
    docker("rm", "-f", NAME)
    started = docker("run", "-d", "--name", NAME, "--platform", platform, "-p", f"127.0.0.1:{PORT}:8080",
                     "-v", f"{dist / folder}:{mount}:ro", image, handler)
    if started.returncode != 0:
        return {"scenario": label, "started": False, "error": started.stderr.strip()}
    result = {"scenario": label, "build": folder, "image": image, "platform": platform, "expected": expected,
              "started": wait_ready(), "responses": {}}
    for name, event in EVENTS.items():
        try:
            status, body = invoke(event)
        except OSError as err:
            status, body = 0, f"{type(err).__name__}: {err}"
        if isinstance(body, dict) and "body" in body:
            body = {"statusCode": body.get("statusCode"), "body": json.loads(body["body"])}
        result["responses"][name] = {"http": status, "result": body}
    time.sleep(1)
    logs = docker("logs", NAME)
    result["log"] = [line for line in (logs.stdout + logs.stderr).splitlines() if line.strip()]
    docker("rm", "-f", NAME)
    return result


def worked(result) -> bool:
    responses = result.get("responses", {})
    return bool(responses) and all(isinstance(r["result"], dict) and "statusCode" in r["result"]
                                   for r in responses.values())


def main() -> int:
    results = [run(*scenario) for scenario in SCENARIOS]
    reference = results[1]["responses"]
    status = 0
    lines = []
    for result in results:
        ok = worked(result)
        same = ok and all(result["responses"][k]["result"] == reference[k]["result"] for k in reference)
        result["worked"], result["same_as_reference"] = ok, same
        if result["expected"] is not None and ok != result["expected"]:
            status = 1
            verdict = "UNEXPECTED"
        else:
            verdict = "as expected" if result["expected"] is not None else "recorded"
        codes = ", ".join(f"{k} {v['result'].get('statusCode') if isinstance(v['result'], dict) else 'error'}"
                          for k, v in result["responses"].items())
        lines.append(f"{result['scenario']:<48} worked={str(ok):<5} same={str(same):<5} [{codes}] {verdict}")
        if not ok:
            lines.extend(f"    | {line}" for line in result["log"][-6:])
    (out / "emulator.json").write_text(json.dumps(results, indent=2) + "\n")
    print("\n".join(lines))
    return status


if __name__ == "__main__":
    sys.exit(main())
