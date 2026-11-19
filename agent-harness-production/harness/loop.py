"""The loop. Everything a tool call passes through is in ``_execute``, in the order it happens."""
from __future__ import annotations

import concurrent.futures
import json
import random
import time
from dataclasses import dataclass
from typing import Any

from opentelemetry import trace
from opentelemetry.trace import SpanKind, Status, StatusCode

from .budget import Budget
from .model import Message, Model
from .policy import Policy
from .store import Store
from .tools import Call, Registry, Tool, TransientError

_tracer = trace.get_tracer("agent-harness")
_pool = concurrent.futures.ThreadPoolExecutor(max_workers=8, thread_name_prefix="tool")


@dataclass
class Result:
    status: str          # "done", or "stopped: <limit>"
    answer: str
    messages: list[Message]
    model_calls: int
    tool_calls: int


def run_agent(model: Model, registry: Registry, task: str, *, run_id: str, store: Store,
              policy: Policy | None = None, budget: Budget | None = None, agent_name: str = "desk") -> Result:
    policy, budget = policy or Policy(), budget or Budget()
    saved = store.load(run_id)
    messages: list[Message] = saved[1] if saved else [{"role": "user", "content": task}]

    with _tracer.start_as_current_span(f"invoke_agent {agent_name}", kind=SpanKind.INTERNAL) as span:
        span.set_attribute("gen_ai.operation.name", "invoke_agent")
        span.set_attribute("gen_ai.agent.name", agent_name)
        span.set_attribute("gen_ai.conversation.id", run_id)
        span.set_attribute("harness.resumed", saved is not None)
        while True:
            # A restart can find tool calls that were asked for and never answered. Answer those first.
            for pending in _unanswered(messages):
                messages.append({"role": "tool", "tool_call_id": pending["id"], "content": _execute(pending, registry, policy, budget, store, run_id, agent_name)})
                store.save(run_id, "running", messages)

            last = messages[-1]
            if last["role"] == "assistant" and not last.get("tool_calls"):
                store.save(run_id, "done", messages)
                return Result("done", str(last["content"]), messages, budget.model_calls, budget.tool_calls)

            if (limit := budget.exhausted()) is not None:
                span.set_attribute("harness.stopped_by", limit)
                store.save(run_id, f"stopped: {limit}", messages)
                return Result(f"stopped: {limit}", "", messages, budget.model_calls, budget.tool_calls)

            _compact(messages, budget.max_context_chars)
            with _tracer.start_as_current_span(f"chat {model.name}", kind=SpanKind.CLIENT) as chat:
                chat.set_attribute("gen_ai.operation.name", "chat")
                chat.set_attribute("gen_ai.request.model", model.name)
                budget.model_calls += 1
                messages.append(model.complete(messages, registry.describe()))
            store.save(run_id, "running", messages)


def _execute(call: dict[str, Any], registry: Registry, policy: Policy, budget: Budget, store: Store, run_id: str, agent_name: str) -> str:
    """One tool call, from the model's request to the text the model gets back."""
    name = str(call.get("name"))
    with _tracer.start_as_current_span(f"execute_tool {name}", kind=SpanKind.INTERNAL) as span:
        span.set_attribute("gen_ai.operation.name", "execute_tool")
        span.set_attribute("gen_ai.tool.name", name)
        span.set_attribute("gen_ai.tool.call.id", str(call.get("id")))
        span.set_attribute("gen_ai.agent.name", agent_name)

        def refuse(kind: str, text: str) -> str:
            span.set_attribute("error.type", kind)
            span.set_status(Status(StatusCode.ERROR, text[:200]))
            return f"error: {text}"

        # 1. Does the tool exist?
        tool = registry.get(name)
        if tool is None:
            return refuse("unknown_tool", f"there is no tool named '{name}'. Available: {', '.join(registry.names())}")

        # 2. Are the arguments JSON, and do they fit the schema?
        try:
            arguments = json.loads(call.get("arguments") or "{}")
        except json.JSONDecodeError as error:
            return refuse("invalid_json", f"arguments are not valid JSON ({error.msg})")
        if not isinstance(arguments, dict):
            return refuse("invalid_arguments", "arguments must be a JSON object")
        if problems := registry.problems(name, arguments):
            return refuse("invalid_arguments", "invalid arguments: " + "; ".join(problems[:5]))

        # 3. Has this exact write already happened? Then report it and do not repeat it.
        about = Call(run_id=run_id, call_id=str(call.get("id")))
        if tool.effect == "write" and (earlier := store.effect(about.idempotency_key)) is not None:
            span.set_attribute("harness.replayed", True)
            return earlier

        # 4. Is it allowed?
        if (reason := policy.refusal(tool, arguments)) is not None:
            return refuse("not_approved", reason)

        # 5. Is there budget left?
        if budget.tool_calls >= budget.max_tool_calls:
            return refuse("budget", "the tool call budget for this run is used up")
        budget.tool_calls += 1

        # 6. Run it: with a time limit, and again if the failure is the kind that passes.
        try:
            raw = _run_with_retries(tool, arguments, about, span)
        except concurrent.futures.TimeoutError:
            return refuse("timeout", f"'{name}' did not answer within {tool.timeout_s:g} s")
        except Exception as error:  # noqa: BLE001 - the model gets a short reason, the trace gets the rest
            span.record_exception(error)
            return refuse(type(error).__name__, f"'{name}' failed: {type(error).__name__}: {str(error)[:200]}")

        # 7. Keep the result to a size the context can afford.
        text = raw if isinstance(raw, str) else json.dumps(raw, default=str)
        if len(text) > budget.max_result_chars:
            span.set_attribute("harness.truncated_from", len(text))
            text = text[: budget.max_result_chars] + f"\n[truncated: {len(text) - budget.max_result_chars} more characters. Ask for less.]"

        # 8. Remember a write, so a restart does not do it twice.
        if tool.effect == "write":
            store.record_effect(about.idempotency_key, text)
        return text


def _run_with_retries(tool: Tool, arguments: dict[str, Any], about: Call, span: trace.Span) -> Any:
    for attempt in range(1, tool.attempts + 1):
        try:
            # The wait is bounded. The thread is not killed: code that must be stopped belongs in the sandbox.
            return _pool.submit(tool.run, arguments, about).result(timeout=tool.timeout_s)
        except TransientError:
            if attempt == tool.attempts:
                raise
            span.add_event("retry", {"attempt": attempt})
            time.sleep(min(2.0, 0.05 * 2 ** attempt) * (0.5 + random.random() / 2))
    raise AssertionError("unreachable")


def _unanswered(messages: list[Message]) -> list[dict[str, Any]]:
    """Tool calls in the last assistant message that have no result yet."""
    for index in range(len(messages) - 1, -1, -1):
        if messages[index]["role"] == "assistant":
            answered = {m["tool_call_id"] for m in messages[index + 1:] if m["role"] == "tool"}
            return [c for c in messages[index].get("tool_calls") or [] if c["id"] not in answered]
    return []


def _compact(messages: list[Message], limit: int) -> None:
    """When the conversation is too long, shrink the oldest tool results first. The newest one is kept whole."""
    size = sum(len(str(m.get("content") or "")) for m in messages)
    results = [m for m in messages if m["role"] == "tool"]
    for message in results[:-1]:
        if size <= limit:
            return
        content = str(message["content"])
        if len(content) > 200:
            message["content"] = content[:120] + f" [shortened: {len(content) - 120} characters dropped to save context]"
            size -= len(content) - len(message["content"])
