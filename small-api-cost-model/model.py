"""Monthly cost of one small HTTP API on ECS Express Mode, App Runner and Lambda.

    python model.py                 the tables used in the article
    python model.py --json out.json the same numbers as data

This is arithmetic on published list prices. Nothing is deployed and nothing is measured. The traffic shape, the
CPU each request needs and the response sizes are assumptions, set in Workload below and printed with the result.
Standard library only.
"""
from __future__ import annotations

import dataclasses
import json
import math
import pathlib
import sys

PRICES = json.loads((pathlib.Path(__file__).parent / "prices.json").read_text(encoding="utf-8"))
HOURS = PRICES["hours_per_month"]
DAYS = HOURS / 24


@dataclasses.dataclass(frozen=True)
class Workload:
    """One API, described by what it is asked to do in a month."""
    requests_per_month: float
    duration_ms: float = 60          # time to answer one request, as Lambda would bill it
    cpu_ms: float = 15               # CPU time one request needs; the rest of the duration is waiting on I/O
    response_kb: float = 4           # response body, for load balancer bytes and data transfer
    log_bytes_per_request: float = 300
    busy_hours_per_day: float = 10   # the working day
    busy_share: float = 0.85         # share of the day's requests that arrive in the busy hours
    peak_to_average: float = 3.0     # the busiest minute of the busy hours against their average

    def rate(self, busy: bool) -> float:
        """Average requests per second in the busy hours, or in the quiet ones."""
        per_day = self.requests_per_month / DAYS
        hours, share = (self.busy_hours_per_day, self.busy_share) if busy else (24 - self.busy_hours_per_day, 1 - self.busy_share)
        return per_day * share / (hours * 3600)

    def hours(self, busy: bool) -> float:
        return DAYS * (self.busy_hours_per_day if busy else 24 - self.busy_hours_per_day)


def fargate_cost(task_seconds: float, vcpu: float, gb: float, arch: str = "x86") -> float:
    price = PRICES["fargate"][arch]
    return task_seconds * (vcpu * price["vcpu_second"] + gb * price["gb_second"])


def app_runner_cost(provisioned_hours: float, active_hours: float, vcpu: float, gb: float) -> float:
    """Memory for every provisioned instance-hour, plus vCPU for the hours an instance is active."""
    price = PRICES["apprunner"]
    return provisioned_hours * gb * price["provisioned_gb_hour"] + active_hours * vcpu * price["active_vcpu_hour"]


def lambda_cost(requests: float, duration_ms: float, memory_mb: int, arch: str = "arm", free_tier: bool = False) -> dict[str, float]:
    price = PRICES["lambda"]
    gb_seconds = requests * duration_ms / 1000 * memory_mb / 1024
    if free_tier:
        requests, gb_seconds = max(0.0, requests - price["free_tier"]["requests"]), max(0.0, gb_seconds - price["free_tier"]["gb_seconds"])
    return {"requests": requests / 1e6 * price["million_requests"], "compute": gb_seconds * price[arch]["gb_second"]}


def common(w: Workload) -> dict[str, float]:
    """Costs every option pays in the same way: logs and data out to the internet."""
    return {
        "logs": w.requests_per_month * w.log_bytes_per_request / 1e9 * PRICES["logs"]["ingest_gb"],
        "data transfer out": w.requests_per_month * w.response_kb / 1e6 * PRICES["data_transfer_out"]["gb"],
    }


def instances_needed(w: Workload, vcpu: float, minimum: int, cpu_target: float = 0.60) -> dict[bool, int]:
    """Instances that keep average CPU at the scaling target during the busiest minute of each period."""
    return {busy: max(minimum, math.ceil(w.rate(busy) * w.peak_to_average * w.cpu_ms / 1000 / (vcpu * cpu_target))) for busy in (True, False)}


def ecs_express(w: Workload, vcpu: float = 0.25, gb: float = 0.5, min_tasks: int = 1, arch: str = "x86",
                services_on_load_balancer: int = 1, availability_zones: int = 2, public_subnets: bool = True) -> dict[str, float]:
    """Fargate tasks behind an Application Load Balancer, which is what Express Mode creates. It cannot scale to zero."""
    tasks = instances_needed(w, vcpu, min_tasks)
    task_hours = sum(tasks[busy] * w.hours(busy) for busy in (True, False))
    lcu_hours = 0.0
    for busy in (True, False):
        rate = w.rate(busy)
        dimensions = [
            rate / PRICES["alb"]["lcu"]["new_connections_per_second"],                       # one new connection per request: the expensive end
            rate * w.duration_ms / 1000 / PRICES["alb"]["lcu"]["active_connections"],
            rate * 3600 * (w.response_kb + 1) / 1e6 / PRICES["alb"]["lcu"]["processed_gb_per_hour"],
            rate * max(0, services_on_load_balancer - PRICES["alb"]["lcu"]["free_rules"]) / PRICES["alb"]["lcu"]["rule_evaluations_per_second"],
        ]
        lcu_hours += max(dimensions) * w.hours(busy)
    # The load balancer's hourly charge and its addresses are shared by every Express Mode service on it; its LCUs are this service's own.
    shared = (PRICES["alb"]["hour"] + (availability_zones * PRICES["public_ipv4"]["hour"] if public_subnets else 0)) * HOURS / services_on_load_balancer
    return {
        "compute": fargate_cost(task_hours * 3600, vcpu, gb, arch),
        "load balancer": shared + lcu_hours * PRICES["alb"]["lcu_hour"],
        "task public IPv4": task_hours * PRICES["public_ipv4"]["hour"] if public_subnets else 0.0,
        **common(w),
    }


def app_runner(w: Workload, vcpu: float = 0.25, gb: float = 0.5, min_instances: int = 1) -> dict[str, float]:
    """Memory is paid for every provisioned instance all month; vCPU only while an instance is handling requests."""
    instances = instances_needed(w, vcpu, min_instances)
    provisioned_hours = sum(instances[busy] * w.hours(busy) for busy in (True, False))
    active_hours = 0.0
    for busy in (True, False):
        # Assumption: a minute with at least one request is an active minute for one instance. With requests
        # arriving at random, that is 1 - e^(-requests per minute per instance) of the minutes.
        per_instance_per_minute = w.rate(busy) * 60 / instances[busy]
        active_hours += instances[busy] * w.hours(busy) * (1 - math.exp(-per_instance_per_minute))
    return {
        "compute": app_runner_cost(provisioned_hours, active_hours, vcpu, gb),
        **common(w),
    }


def lambda_function(w: Workload, memory_mb: int = 512, arch: str = "arm", http_api: bool = False,
                    provisioned_concurrency: int = 0, free_tier: bool = False) -> dict[str, float]:
    """Per request and per millisecond. A function URL in front costs nothing; an API Gateway HTTP API is charged per request."""
    cost = lambda_cost(w.requests_per_month, w.duration_ms, memory_mb, arch, free_tier)
    if provisioned_concurrency:
        kept = PRICES["lambda"]["provisioned_concurrency"]["x86"]       # the model prices provisioned concurrency on x86 only
        gb = memory_mb / 1024
        cost["provisioned concurrency"] = provisioned_concurrency * gb * HOURS * 3600 * kept["gb_second"]
        cost["compute"] = w.requests_per_month * w.duration_ms / 1000 * gb * kept["duration_gb_second"]
    if http_api:
        cost["HTTP API"] = w.requests_per_month / 1e6 * PRICES["http_api"]["million_requests"]
    return {**cost, **common(w)}


OPTIONS = {
    "ECS Express, 1 task": lambda w: ecs_express(w),
    "ECS Express, 2 tasks": lambda w: ecs_express(w, min_tasks=2),
    "ECS Express, 2 tasks, Graviton, ALB shared by 5": lambda w: ecs_express(w, min_tasks=2, arch="arm", services_on_load_balancer=5),
    "App Runner, 1 instance": lambda w: app_runner(w),
    "Lambda, function URL": lambda w: lambda_function(w),
    "Lambda, HTTP API": lambda w: lambda_function(w, http_api=True),
    "Lambda, 1 provisioned, function URL": lambda w: lambda_function(w, arch="x86", provisioned_concurrency=1),
}
VOLUMES = [100_000, 1_000_000, 5_000_000, 20_000_000, 50_000_000]


def total(parts: dict[str, float]) -> float:
    return sum(parts.values())


def break_even(cheap_when_small, cheap_when_large, low: float = 1e4, high: float = 1e10, **workload) -> float | None:
    """Requests per month at which two options cost the same, by bisection. None if they never cross in the range."""
    def gap(requests: float) -> float:
        w = Workload(requests_per_month=requests, **workload)
        return total(cheap_when_small(w)) - total(cheap_when_large(w))
    if gap(low) > 0 or gap(high) < 0:
        return None
    for _ in range(80):
        middle = math.sqrt(low * high)
        low, high = (middle, high) if gap(middle) < 0 else (low, middle)
    return low


def report() -> dict:
    result: dict = {"assumptions": dataclasses.asdict(Workload(0)), "monthly_usd": {}, "break_even_requests_per_month": {}, "detail": {}}
    print("Monthly cost in USD, US East (N. Virginia) list prices, by requests per month\n")
    print(f"{'':50}" + "".join(f"{volume / 1e6:>9g}M" for volume in VOLUMES))
    for name, option in OPTIONS.items():
        costs = [total(option(Workload(volume))) for volume in VOLUMES]
        result["monthly_usd"][name] = dict(zip(map(str, VOLUMES), [round(c, 2) for c in costs]))
        print(f"{name:50}" + "".join(f"{cost:>10.2f}" for cost in costs))

    print("\nWhere the money goes at 5 million requests a month\n")
    for name, option in OPTIONS.items():
        parts = option(Workload(5_000_000))
        result["detail"][name] = {key: round(value, 2) for key, value in parts.items()}
        print(f"{name:50}{total(parts):>9.2f}  " + ", ".join(f"{key} {value:.2f}" for key, value in parts.items() if value >= 0.005))

    print("\nRequests per month above which a container option is cheaper than Lambda with a function URL")
    print("Each request needs 15 ms of CPU; what changes is how long it takes in total, and how spiky the traffic is\n")
    names = ("ECS Express, 1 task", "ECS Express, 2 tasks", "App Runner, 1 instance")
    for peak in (3.0, 1.5):
        print(f"  busiest minute at {peak:g} times the average")
        for duration in (20, 60, 200, 500, 1000):
            row = {}
            for name in names:
                crossing = break_even(OPTIONS["Lambda, function URL"], OPTIONS[name], duration_ms=duration, cpu_ms=min(15, duration), peak_to_average=peak)
                row[name] = None if crossing is None else round(crossing)
            result["break_even_requests_per_month"][f"peak {peak:g}, {duration} ms"] = row
            print(f"    {duration:>4} ms per request:  " + ",  ".join(f"{name}: {'never' if value is None else f'{value / 1e6:.1f}M'}" for name, value in row.items()))

    small = fargate_cost(3600, 0.25, 0.5)
    result["task_hour_usd"] = {"compute": round(small, 5), "public_ipv4": PRICES["public_ipv4"]["hour"]}
    print(f"\nOne 0.25 vCPU, 0.5 GB Fargate task for an hour: {small:.5f} for compute and {PRICES['public_ipv4']['hour']:.3f} for its public IPv4 address,")
    print(f"so the address adds {PRICES['public_ipv4']['hour'] / small:.0%} to the price of the task")

    print("\nThe floor: what each option costs with no traffic at all\n")
    idle = Workload(0)
    result["floor_usd"] = {name: round(total(option(idle)), 2) for name, option in OPTIONS.items()}
    for name, cost in result["floor_usd"].items():
        print(f"  {name:50}{cost:>9.2f}")
    return result


if __name__ == "__main__":
    data = report()
    if "--json" in sys.argv:
        pathlib.Path(sys.argv[sys.argv.index("--json") + 1]).write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
