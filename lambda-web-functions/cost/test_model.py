"""python test_model.py

The model is checked against the worked examples AWS publishes on its own pricing pages. If it cannot
reproduce those to the cent, nothing else it prints deserves to be read.
"""
import sys

from model import SCENARIOS, Workload, app_runner, compare, event_function, web_function

passed = failed = 0


def check(name: str, actual: float, expected: float, tolerance: float = 0.011) -> None:
    global passed, failed
    ok = abs(actual - expected) <= tolerance
    passed += ok
    failed += not ok
    print(f"{'ok  ' if ok else 'FAIL'}  {name}: {actual:,.2f} (published {expected:,.2f})")


# Lambda pricing page, Web Functions examples 1 to 4: one environment for 30 days.
published = [
    ("AWS example 1, server-side rendered app", Workload("", 15_000_000, 40, 0, 0.49, 24), 25.78),
    ("AWS example 2, I/O-heavy API", Workload("", 10_000_000, 50, 0, 0.29, 24), 19.61),
    ("AWS example 3, authorization middleware", Workload("", 100_000_000, 12, 0, 0.14, 24), 64.56),
    ("AWS example 4, LLM streaming endpoint", Workload("", 5_000_000, 200, 3000, 0.50, 24), 33.94),
]
for name, workload, total in published:
    check(name, web_function(workload)["total"], total)

# App Runner pricing page, example 2: 1 vCPU and 2 GB, active 8 hours a day, memory provisioned all day.
# AWS prints $25.50 from daily figures rounded to cents; unrounded arithmetic gives $25.44.
runner = app_runner(Workload("", 80 * 8 * 3600 * 30, 0, 100, 2.0, 8))
check("App Runner example 2, lightweight API (AWS rounds daily figures)", runner["total"], 25.50, tolerance=0.07)

# Event function arithmetic: 1M requests of 1 s at 1 GB on Arm is 1,000,000 GB-seconds.
check("event function, 1M requests x 1 s x 1 GB on Arm", event_function(Workload("", 1_000_000, 0, 1000, 1, 24), 1.0)["total"], 13.33 + 0.20)
check("the same behind an HTTP API", event_function(Workload("", 1_000_000, 0, 1000, 1, 24), 1.0, http_api=True)["total"], 13.33 + 0.20 + 1.00)

rows = {row["workload"]: row for row in map(compare, SCENARIOS)}
io, streaming, cpu, tool = (rows[w.name] for w in SCENARIOS)
checks = [
    ("I/O-heavy: the web function costs less than the event function", io["web_function_always_on"] < io["event_function_url_512mb"]),
    ("streaming: the gap is widest where requests wait longest", streaming["event_function_url_512mb"] / streaming["web_function_always_on"] > io["event_function_url_512mb"] / io["web_function_always_on"]),
    ("CPU-bound: the web function is the more expensive of the two", cpu["web_function_always_on"] > cpu["event_function_url_512mb"]),
    ("low traffic: an always-on environment costs more than paying per request", tool["web_function_always_on"] > tool["event_function_url_512mb"]),
    ("an HTTP API adds exactly its per-request charge", abs(io["event_function_http_api_512mb"] - io["event_function_url_512mb"] - 10.00) < 0.011),
]
for name, ok in checks:
    passed += ok
    failed += not ok
    print(f"{'ok  ' if ok else 'FAIL'}  {name}")

print(f"\n{passed} of {passed + failed} checks passed")
sys.exit(1 if failed else 0)
