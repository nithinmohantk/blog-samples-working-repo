"""Monthly cost of one HTTP workload on four ways of running it on AWS.

    python model.py                  the comparison table for the scenarios in this file
    python model.py --json           the same as JSON

The point of the model is the shape of each bill, not the totals: which quantity each option meters.
  web function        requests + CPU time actually used + memory for as long as an environment exists
  event function      requests + memory x wall-clock duration of every request
  HTTP API in front   the event function, plus a charge per request
  App Runner          vCPU and memory per hour while instances are active, memory per hour otherwise
Rates are in rates.json. Free tiers and data transfer are excluded.
"""
from __future__ import annotations

import argparse
import json
import math
import pathlib
from dataclasses import dataclass

RATES = json.loads(pathlib.Path(__file__).with_name("rates.json").read_text(encoding="utf-8"))
SECONDS_PER_MONTH = 30 * 24 * 3600


@dataclass(frozen=True)
class Workload:
    name: str
    requests: int               # per 30-day month
    cpu_ms: float               # CPU time one request actually uses
    duration_ms: float          # how long one request takes end to end
    memory_gb: float            # memory the server process uses
    busy_hours_per_day: float   # hours a day with traffic; outside them there is none


def web_function(w: Workload, environments: float = 1.0, always_on: bool = True) -> dict:
    """Requests, active CPU, and memory for the life of each environment."""
    rates = RATES["web_function"]
    alive_seconds = SECONDS_PER_MONTH if always_on else w.busy_hours_per_day * 3600 * 30
    cpu = w.requests * w.cpu_ms / 1000 * rates["active_vcpu_second"]
    memory = w.memory_gb * alive_seconds * environments * rates["memory_gb_second"]
    requests = w.requests / 1e6 * rates["per_million_requests"]
    return {"cpu": cpu, "memory": memory, "requests": requests, "total": cpu + memory + requests}


def event_function(w: Workload, configured_memory_gb: float, architecture: str = "arm", http_api: bool = False) -> dict:
    """Requests, and configured memory for the whole duration of every request, waiting included."""
    rates = RATES["event_function"]
    compute = w.requests * w.duration_ms / 1000 * configured_memory_gb * rates[f"gb_second_{architecture}"]
    requests = w.requests / 1e6 * rates["per_million_requests"]
    gateway = w.requests / 1e6 * RATES["http_api"]["per_million_requests"] if http_api else 0.0
    return {"compute": compute, "requests": requests, "gateway": gateway, "total": compute + requests + gateway}


def app_runner(w: Workload, vcpu: float = 1.0, memory_gb: float = 2.0, concurrency: int = 80) -> dict:
    """Instances are charged for vCPU and memory while active and for memory alone while idle."""
    rates = RATES["app_runner"]
    busy_seconds = w.busy_hours_per_day * 3600 * 30
    in_flight = w.requests * w.duration_ms / 1000 / busy_seconds if busy_seconds else 0.0
    instances = max(1, math.ceil(in_flight / concurrency))
    active_hours = w.busy_hours_per_day * 30
    idle_hours = 24 * 30 - active_hours
    active = instances * active_hours * (vcpu * rates["active_vcpu_hour"] + memory_gb * rates["gb_hour"])
    idle = idle_hours * memory_gb * rates["gb_hour"]
    return {"active": active, "idle": idle, "instances": instances, "total": active + idle}


SCENARIOS = [
    Workload("I/O-heavy API: 10M requests, 50 ms CPU inside a 300 ms request", 10_000_000, 50, 300, 0.29, 24),
    Workload("Streaming endpoint: 5M requests, 200 ms CPU inside a 3 s response", 5_000_000, 200, 3000, 0.50, 24),
    Workload("CPU-bound API: 10M requests, 280 ms CPU inside a 300 ms request", 10_000_000, 280, 300, 0.29, 24),
    Workload("Internal tool: 60,000 requests in office hours, 50 ms CPU inside 300 ms", 60_000, 50, 300, 0.29, 8),
]


def compare(w: Workload) -> dict:
    return {
        "workload": w.name,
        "web_function_always_on": round(web_function(w)["total"], 2),
        "web_function_scaled_to_zero_off_hours": round(web_function(w, always_on=False)["total"], 2),
        "event_function_url_512mb": round(event_function(w, 0.5)["total"], 2),
        "event_function_http_api_512mb": round(event_function(w, 0.5, http_api=True)["total"], 2),
        "app_runner_1vcpu_2gb": round(app_runner(w)["total"], 2),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    rows = [compare(w) for w in SCENARIOS]
    if parser.parse_args().json:
        print(json.dumps(rows, indent=2))
        return
    for row in rows:
        print(row["workload"])
        for key, value in row.items():
            if key != "workload":
                print(f"  {key:<40} ${value:>10,.2f}")
        print()


if __name__ == "__main__":
    main()
