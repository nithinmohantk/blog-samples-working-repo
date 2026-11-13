"""Runs each published build of the function in the AWS Lambda base image, whose entry point is the Lambda
Runtime Interface Emulator, and invokes it over HTTP as Lambda would.

    python emulate.py <output dir> <dotnet image> <provided image>

It checks that every build gives the same answers, and it times a first request to a new container and then warm
requests. These are timings on the machine that runs this script, with Docker's limits standing in for Lambda's.
They compare the builds with each other. They are not Lambda cold-start figures. Standard library only.
"""
import json
import pathlib
import re
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request

out = pathlib.Path(sys.argv[1]).resolve()
dotnet_image, provided_image = sys.argv[2], sys.argv[3]
here = pathlib.Path(__file__).resolve().parent.parent
events = {path.stem: path.read_bytes() for path in sorted((here / "events").glob("*.json"))}
PORT, NAME, COLD_STARTS, WARM_REQUESTS = 9100, "lambda-emulated", 7, 200
URL = f"http://127.0.0.1:{PORT}/2015-03-31/functions/function/invocations"
BUILDS = [  # label, publish folder, image, handler argument
    ("managed runtime", "jit", dotnet_image, "Quotes.Function"),
    ("managed runtime, ReadyToRun", "r2r", dotnet_image, "Quotes.Function"),
    ("Native AOT", "aot", provided_image, "bootstrap"),
]
REFLECTION = [
    ("managed runtime, reflection JSON", "jit-reflection", dotnet_image, "Quotes.Function"),
    ("Native AOT, reflection JSON", "aot-reflection", provided_image, "bootstrap"),
]


def docker(*arguments: str) -> str:
    return subprocess.run(["docker", *arguments], capture_output=True, text=True).stdout.strip()


def invoke(event: bytes, timeout: float = 30) -> tuple[float, dict]:
    request = urllib.request.Request(URL, data=event, headers={"Content-Type": "application/json"})
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = json.load(response)
    return (time.perf_counter() - started) * 1000, body


def start(folder: str, image: str, handler: str) -> float:
    """Starts a container the way Lambda sizes a 512 MB function, and returns when it was asked to start."""
    docker("rm", "-f", NAME)
    began = time.perf_counter()
    docker("run", "-d", "--name", NAME, "-p", f"127.0.0.1:{PORT}:8080", "--memory", "512m", "--cpus", "1",
           "-e", "AWS_LAMBDA_FUNCTION_MEMORY_SIZE=512", "-v", f"{out / 'publish' / folder}:/var/task:ro", image, handler)
    return began


def first_request(event: bytes) -> tuple[float, dict]:
    """The emulator starts the function's process on the first invocation, so this request pays for initialisation."""
    deadline = time.perf_counter() + 60
    while True:
        try:
            return invoke(event, timeout=60)
        except urllib.error.HTTPError as error:
            logs = subprocess.run(["docker", "logs", NAME], capture_output=True, text=True)
            print(f"HTTP {error.code} {error.read()[:300]!r}; container log follows\n" + (logs.stdout + logs.stderr)[-3000:])
            raise
        except (urllib.error.URLError, ConnectionError, OSError):
            if time.perf_counter() > deadline:
                logs = subprocess.run(["docker", "logs", NAME], capture_output=True, text=True)
                print("the function did not answer; container log follows\n" + (logs.stdout + logs.stderr)[-3000:])
                raise
            time.sleep(0.01)


def comparable(response: dict) -> dict:
    """The response without the header that names the instance, which is meant to differ."""
    if "statusCode" not in response:
        return {"error": response.get("errorType", "unknown")}
    return {"statusCode": response["statusCode"], "body": response.get("body")}


results: dict = {"images": {"dotnet": dotnet_image, "provided": provided_image}, "builds": {}, "answers": {}, "reflection": {}}
failed = False

print("== the same six requests to each build")
for label, folder, image, handler in BUILDS:
    start(folder, image, handler)
    first_request(events["1-quote"])
    results["answers"][label] = {name: comparable(invoke(event)[1]) for name, event in events.items()}
    docker("rm", "-f", NAME)
reference = results["answers"][BUILDS[0][0]]
for name in events:
    answer = reference[name]
    same = all(results["answers"][label][name] == answer for label, *_ in BUILDS)
    failed |= not same
    print(f"{'ok  ' if same else 'FAIL'}  {name:20} {answer.get('statusCode', answer.get('error'))}  {(answer.get('body') or '')[:96]}")
print(f"{'ok  ' if not failed else 'FAIL'}  all three builds gave byte-identical bodies and the same status for every request")

print(f"\n== first request to a new container ({COLD_STARTS} containers each), then {WARM_REQUESTS} warm requests")
print(f"{'build':30} {'start to first answer':>22} {'first request':>15} {'reported init':>14} {'warm p50':>9} {'warm p99':>9} {'memory':>8}")
for label, folder, image, handler in BUILDS:
    to_answer, first, reported, warm, memory = [], [], [], [], []
    for _ in range(COLD_STARTS):
        began = start(folder, image, handler)
        milliseconds, _ = first_request(events["1-quote"])
        to_answer.append((time.perf_counter() - began) * 1000)
        first.append(milliseconds)
        warm += [invoke(events["1-quote"])[0] for _ in range(WARM_REQUESTS // COLD_STARTS + 1)]
        logs = subprocess.run(["docker", "logs", NAME], capture_output=True, text=True)
        reported += [float(value) for value in re.findall(r"Init Duration: ([\d.]+) ms", logs.stdout + logs.stderr)[:1]]
        usage = docker("stats", "--no-stream", "--format", "{{.MemUsage}}", NAME).split("/")[0].strip()
        if usage.endswith("MiB"):
            memory.append(float(usage[:-3]))
        docker("rm", "-f", NAME)
    warm.sort()
    row = {
        "start_to_first_answer_ms": round(statistics.median(to_answer)), "first_request_ms": round(statistics.median(first)),
        "first_request_ms_min_max": [round(min(first)), round(max(first))],
        "reported_init_ms": round(statistics.median(reported)) if reported else None,
        "warm_p50_ms": round(statistics.median(warm), 2), "warm_p99_ms": round(warm[int(len(warm) * 0.99) - 1], 2),
        "memory_mib": round(statistics.median(memory)) if memory else None,
    }
    results["builds"][label] = row
    print(f"{label:30} {row['start_to_first_answer_ms']:>19} ms {row['first_request_ms']:>12} ms {str(row['reported_init_ms'] or '-'):>11} ms "
          f"{row['warm_p50_ms']:>6} ms {row['warm_p99_ms']:>6} ms {str(row['memory_mib'] or '-'):>4} MiB")

print("\n== the same function with reflection-based JSON")
for label, folder, image, handler in REFLECTION:
    start(folder, image, handler)
    try:
        _, response = first_request(events["1-quote"])
    except Exception as error:  # noqa: BLE001 - a build that cannot answer is the finding
        response = {"errorType": type(error).__name__, "errorMessage": str(error)}
    logs = subprocess.run(["docker", "logs", NAME], capture_output=True, text=True)
    docker("rm", "-f", NAME)
    outcome = f"{response['statusCode']} {response.get('body', '')[:70]}" if "statusCode" in response else f"{response.get('errorType')}: {str(response.get('errorMessage'))[:150]}"
    results["reflection"][label] = {"answered": "statusCode" in response, "outcome": outcome}
    print(f"  {label:34} {outcome}")
    if "statusCode" not in response:
        (out / f"emulator-{folder}.log").write_text(logs.stdout + logs.stderr, encoding="utf-8")
expected = results["reflection"][REFLECTION[0][0]]["answered"] and not results["reflection"][REFLECTION[1][0]]["answered"]
failed |= not expected
print(f"{'ok  ' if expected else 'FAIL'}  reflection JSON works on the managed runtime and fails as Native AOT")

(out / "emulator.json").write_text(json.dumps(results, indent=1) + "\n", encoding="utf-8")
sys.exit(1 if failed else 0)
