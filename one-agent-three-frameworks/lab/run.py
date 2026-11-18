"""Runs every scenario against every framework and prints what happened. Usage: python -m lab.run <output folder>

A scenario is a script for the stand-in model. The frameworks are left at their defaults. Most of the output is
observation: the point is to see what each framework does, not to pass or fail it.
"""
from __future__ import annotations

import asyncio
import json
import logging
import pathlib
import sys
import time
import warnings
from importlib.metadata import version

from . import tools
from .frameworks import FRAMEWORKS
from .standin import StandIn

warnings.filterwarnings("ignore")
logging.disable(logging.CRITICAL)
out = pathlib.Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
results: dict = {}
passed = total = 0

LOOKUP_A = ("lookup_order", {"order_id": "A-100"})
REFUND_A = ("refund_order", {"order_id": "A-100", "amount": 25.0})
SCENARIOS: list[dict] = [
    {"name": "1. The model behaves", "ask": "Refund 25 euro on order A-100.",
     "script": [{"calls": [LOOKUP_A]}, {"calls": [REFUND_A]}, {"text": "Refunded 25.00 on A-100."}]},
    {"name": "2. Two tool calls in one turn", "ask": "What is the status of A-100 and B-200?",
     "script": [{"calls": [LOOKUP_A, ("lookup_order", {"order_id": "B-200"})]}, {"text": "A-100 delivered, B-200 shipped."}]},
    {"name": "2b. The same two calls, with the tool written as an async function", "ask": "What is the status of A-100 and B-200?", "tools": "async",
     "script": [{"calls": [("lookup_order_async", {"order_id": "A-100"}), ("lookup_order_async", {"order_id": "B-200"})]}, {"text": "A-100 delivered, B-200 shipped."}]},
    {"name": "3. The same refund asked for twice in one turn", "ask": "Refund 25 euro on order A-100.",
     "script": [{"calls": [REFUND_A, REFUND_A]}, {"text": "Refunded."}]},
    {"name": "4. A tool raises an exception", "ask": "What is the status of order Z-999?",
     "script": [{"calls": [("lookup_order", {"order_id": "Z-999"})]}, {"text": "I could not find that order."}]},
    {"name": "5. The model calls a tool that does not exist", "ask": "Cancel order A-100.",
     "script": [{"calls": [("cancel_order", {"order_id": "A-100"})]}, {"text": "I cannot cancel orders."}]},
    {"name": "6. A required argument is missing", "ask": "Refund order A-100.",
     "script": [{"calls": [("refund_order", {"order_id": "A-100"})]}, {"text": "How much should I refund?"}]},
    {"name": "7. An argument has the wrong type", "ask": "Refund order A-100.",
     "script": [{"calls": [("refund_order", {"order_id": "A-100", "amount": "twenty-five"})]}, {"text": "The amount must be a number."}]},
    {"name": "8. A number arrives as text", "ask": "Refund 25 euro on order A-100.",
     "script": [{"calls": [("refund_order", {"order_id": "A-100", "amount": "25"})]}, {"text": "Refunded."}]},
    {"name": "9. The arguments are not valid JSON", "ask": "Refund 25 euro on order A-100.", "chat_only": True,
     "script": [{"calls": [("refund_order", '{"order_id": "A-100", "amount": 25')]}, {"text": "Something went wrong."}]},
    {"name": "10. The model returns nothing", "ask": "Hello.", "script": [{"text": ""}]},
    {"name": "11. Two 429 responses, then an answer", "ask": "Hello.",
     "script": [{"status": 429, "message": "Rate limit reached"}, {"status": 429, "message": "Rate limit reached"}, {"text": "Hello."}]},
    {"name": "12. Two 500 responses, then an answer", "ask": "Hello.",
     "script": [{"status": 500, "message": "Internal error"}, {"status": 500, "message": "Internal error"}, {"text": "Hello."}]},
    {"name": "13. 429 for ever", "ask": "Hello.", "script": [{"status": 429, "message": "Rate limit reached", "repeat": True}], "limit": 400},
    {"name": "14. The model never stops calling a tool", "ask": "What is the status of A-100?", "delay": 0.0,
     "script": [{"calls": [LOOKUP_A], "repeat": True}], "limit": 600, "timeout": 300},
]


def check(what: str, ok: bool) -> None:
    global passed, total
    total += 1
    passed += ok
    print(f"{'ok  ' if ok else 'FAIL'}  {what}")


def shorten(text: str, width: int = 150) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= width else text[: width - 3] + "..."


def tool_results(request: dict) -> list[str]:
    """What the framework told the model about the tools it ran, as it appears in a later request."""
    body = request["body"]
    if request["protocol"] == "chat":
        return [message["content"] if isinstance(message.get("content"), str) else json.dumps(message.get("content")) for message in body["messages"] if message["role"] == "tool"]
    return [json.dumps(part["functionResponse"].get("response"), ensure_ascii=False) for content in body["contents"] for part in content.get("parts", []) if "functionResponse" in part]


TOOLSETS = {"sync": [tools.lookup_order, tools.refund_order], "async": [tools.lookup_order_async, tools.refund_order]}
HARDENED = ("4.", "7.", "8.", "11.", "14.")   # the scenarios run a second time with the hardening settings


async def run_one(framework: str, scenario: dict, hardened: bool = False) -> dict:
    script = scenario["script"]
    limit = scenario.get("limit")
    stand_in = StandIn(script)
    tools.reset()
    tools.DELAY = scenario.get("delay", 0.3)
    started = time.perf_counter()
    outcome: dict = {}

    async def stop_at_limit():
        # A scenario that would otherwise never end is cut off once the model has been called this many times.
        while limit and len(stand_in.requests) < limit:
            await asyncio.sleep(0.05)
        if limit:
            raise TimeoutError

    try:
        run = FRAMEWORKS[framework](stand_in.openai_url, stand_in.gemini_url, TOOLSETS[scenario.get("tools", "sync")], hardened)
        work = asyncio.ensure_future(asyncio.wait_for(run(scenario["ask"]), scenario.get("timeout", 120)))
        guard = asyncio.ensure_future(stop_at_limit()) if limit else None
        done, _ = await asyncio.wait([task for task in (work, guard) if task], return_when=asyncio.FIRST_COMPLETED)
        if work in done:
            if guard:
                guard.cancel()
            outcome = {"result": "answered", "text": work.result()}
        else:
            work.cancel()
            outcome = {"result": "cut off", "text": f"still going after {limit} model calls"}
    except asyncio.TimeoutError:
        outcome = {"result": "timed out", "text": f"no result after {scenario.get('timeout', 120)} s"}
    except BaseException as error:  # noqa: BLE001 - what a framework raises is the finding
        outcome = {"result": "raised", "text": f"{type(error).__name__}: {error}"}
    outcome["seconds"] = round(time.perf_counter() - started, 1)
    outcome["model_requests"] = len(stand_in.requests)
    outcome["executions"] = [dict(entry) for entry in tools.LEDGER]
    outcome["told_model"] = tool_results(stand_in.requests[-1]) if len(stand_in.requests) > 1 else []
    outcome["requests"] = stand_in.requests
    stand_in.close()
    return outcome


def show(framework: str, outcome: dict, scenario: dict) -> None:
    executed = ", ".join(f"{e['tool']}({', '.join(f'{k}={v!r}' for k, v in e['arguments'].items())})" for e in outcome["executions"]) or "none"
    print(f"{framework:18} {outcome['result']:9} {outcome['model_requests']:>4} model calls  {outcome['seconds']:>6.1f} s  tools run: {shorten(executed, 110) if len(outcome['executions']) < 6 else str(len(outcome['executions'])) + ' executions'}")
    print(f"{'':18} result: {shorten(outcome['text'], 170)!r}")
    if outcome["told_model"] and len(outcome["executions"]) < 6:
        for told in outcome["told_model"][-2:]:
            print(f"{'':18} told the model: {shorten(told, 170)}")
    if scenario["name"].startswith("2"):
        print(f"{'':18} the two lookups ran {overlap(outcome['executions'])}")


def overlap(executions: list[dict]) -> str:
    if len(executions) < 2 or "finished" not in executions[0]:
        return "-"
    return "at the same time" if executions[1]["started"] < executions[0]["finished"] else "one after the other"


async def main() -> None:
    packages = ["agent-framework-core", "agent-framework-openai", "langchain", "langgraph", "langchain-openai", "langchain-core", "google-adk", "google-genai", "litellm", "openai"]
    print("versions: " + ", ".join(f"{package} {version(package)}" for package in packages))
    print(f"python {sys.version.split()[0]}")
    import agent_framework._tools as af_tools
    import langgraph._internal._config as lg_config
    import openai
    from google.adk.agents.run_config import RunConfig

    print("defaults read from the installed packages: "
          f"Agent Framework max_iterations {af_tools.DEFAULT_MAX_ITERATIONS}, max_consecutive_errors_per_request {af_tools.DEFAULT_MAX_CONSECUTIVE_ERRORS_PER_REQUEST}; "
          f"LangGraph recursion limit {int(lg_config.DEFAULT_RECURSION_LIMIT)} graph steps; ADK max_llm_calls {RunConfig().max_llm_calls}; "
          f"openai client max_retries {openai.DEFAULT_MAX_RETRIES}")
    for scenario in SCENARIOS:
        print(f"\n== {scenario['name']}")
        print(f"   script: {shorten(json.dumps([{k: v for k, v in step.items()} for step in scenario['script']]), 190)}")
        rows = {}
        for framework in FRAMEWORKS:
            if scenario.get("chat_only") and "Gemini" in framework:
                print(f"{framework:18} not applicable: the Gemini API carries arguments as an object, so they cannot be malformed JSON")
                continue
            outcome = await run_one(framework, scenario)
            rows[framework] = outcome
            show(framework, outcome, scenario)
        results[scenario["name"]] = {framework: {key: value for key, value in outcome.items() if key not in ("requests", "executions")} | {"tool_executions": len(outcome["executions"])} for framework, outcome in rows.items()}
        if scenario["name"].startswith("1."):
            happy = rows
            check("all four give the same answer after the same two tool executions and three model calls",
                  all(o["result"] == "answered" and o["text"] == "Refunded 25.00 on A-100." and o["model_requests"] == 3
                      and [e["tool"] for e in o["executions"]] == ["lookup_order", "refund_order"] for o in rows.values()))

    print(f"\n== The same scenarios with a few lines of configuration: at most {8} model calls, tool failures reported without detail, arguments type-checked, retries on")
    hardened_rows: dict = {}
    for scenario in SCENARIOS:
        if not scenario["name"].startswith(HARDENED):
            continue
        print(f"\n-- {scenario['name']}")
        hardened_rows[scenario["name"]] = {}
        for framework in FRAMEWORKS:
            outcome = await run_one(framework, {**scenario, "limit": None, "timeout": 120}, hardened=True)
            hardened_rows[scenario["name"]][framework] = outcome
            show(framework, outcome, scenario)
    results["hardened"] = {name: {framework: {key: value for key, value in outcome.items() if key not in ("requests", "executions")} | {"tool_executions": len(outcome["executions"])} for framework, outcome in rows.items()} for name, rows in hardened_rows.items()}
    loop = hardened_rows["14. The model never stops calling a tool"]
    print("   model calls when capped at eight: " + ", ".join(f"{framework} {o['model_requests']}" for framework, o in loop.items()))
    check("hardened: every framework stops within nine model calls when the model never stops", all(o["model_requests"] <= 9 for o in loop.values()))
    leak = "orders-db-internal"
    failed = hardened_rows["4. A tool raises an exception"]
    check("hardened: a failing tool no longer ends the run, and the database host in its message reaches neither the model nor the caller",
          all(o["result"] == "answered" and leak not in json.dumps(o["told_model"]) + o["text"] for o in failed.values()))
    wrong = hardened_rows["7. An argument has the wrong type"]
    check("hardened: no framework runs the refund when the amount is not a number", all(not o["executions"] for o in wrong.values()))
    retried = hardened_rows["11. Two 429 responses, then an answer"]
    check("hardened: all four answer after two 429 responses", all(o["result"] == "answered" and o["text"] == "Hello." for o in retried.values()))

    print("\n== What each framework sent on the first request of scenario 1")
    shapes = {}
    for framework, outcome in happy.items():
        request = outcome["requests"][0]
        body = request["body"]
        if request["protocol"] == "chat":
            first = body["messages"][0]
            system = f"a '{first['role']}' message"
            declared = next(tool for tool in body["tools"] if tool["function"]["name"] == "refund_order")["function"]
            options = {key: body[key] for key in sorted(body) if key not in ("messages", "tools", "model")}
            result = next(message["content"] for message in outcome["requests"][1]["body"]["messages"] if message["role"] == "tool")
        else:
            system = "the systemInstruction field"
            declared = next(d for tool in body["tools"] for d in tool["functionDeclarations"] if d["name"] == "refund_order")
            options = {key: body[key] for key in sorted(body) if key not in ("contents", "tools", "systemInstruction")}
            result = tool_results(outcome["requests"][1])[0]
        shapes[framework] = {"instructions": system, "options": options, "bytes": len(json.dumps(body)), "refund_order": declared, "tool_result": result, "user_agent": request["headers"].get("user-agent", "")}
        print(f"\n{framework}: {request['path']}, {len(json.dumps(body)):,} bytes, user agent {shorten(request['headers'].get('user-agent', ''), 70)}")
        print(f"  instructions sent as {system}; other request fields: {shorten(json.dumps(options), 150)}")
        print(f"  refund_order as declared to the model: {json.dumps(declared, sort_keys=True)}")
        print(f"  a tool result as sent back: {shorten(result if isinstance(result, str) else json.dumps(result), 150)}")
    results["request_shapes"] = shapes

    print(f"\n{passed} of {total} checks passed")
    (out / "results.json").write_text(json.dumps(results, indent=1, default=str) + "\n", encoding="utf-8")
    sys.exit(0 if passed == total else 1)


asyncio.run(main())
