import json

import httpx
import pytest
from pydantic import BaseModel

import chat_api


def client_with(handler, seen, **kw):
    def wrapped(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)
    return chat_api.make_client(api_key="sk-test", max_retries=kw.pop("max_retries", 0),
                                http_client=httpx.Client(transport=httpx.MockTransport(wrapped)), **kw)


def completion(content=None, finish="stop", refusal=None, tool_calls=None):
    msg = {"role": "assistant", "content": content, "refusal": refusal}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return httpx.Response(200, json={
        "id": "c1", "object": "chat.completion", "created": 1725958800, "model": chat_api.MODEL,
        "choices": [{"index": 0, "finish_reason": finish, "message": msg}],
        "usage": {"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150}})


def tool_call(name, args, id_="call_1"):
    return [{"id": id_, "type": "function", "function": {"name": name, "arguments": args}}]


class OrderLookup(BaseModel):
    order_id: str


def lookup(args: OrderLookup):
    if args.order_id == "boom":
        raise RuntimeError("database down")
    return {"order_id": args.order_id, "status": "shipped"}


TOOLS = [chat_api.Tool("get_order_status", OrderLookup, lookup, "Look up an order's shipping status")]


def test_tool_loop_sends_strict_schema_runs_tool_and_returns_answer():
    seen, replies = [], iter([
        completion(None, finish="tool_calls", tool_calls=tool_call("get_order_status", '{"order_id":"A-17"}')),
        completion("Order A-17 has shipped."),
    ])
    c = client_with(lambda r: next(replies), seen)
    run = chat_api.run_with_tools(c, [{"role": "user", "content": "Where is A-17?"}], TOOLS)
    assert run.answer == "Order A-17 has shipped." and run.steps == 2 and run.calls == [("get_order_status", "ok")]
    first = json.loads(seen[0].content)
    assert first["model"] == "gpt-4o-2024-08-06" and first["parallel_tool_calls"] is False
    fn = first["tools"][0]["function"]
    assert fn["strict"] is True and fn["parameters"]["additionalProperties"] is False
    second = json.loads(seen[1].content)["messages"]
    assert second[1]["tool_calls"][0]["id"] == "call_1"
    assert second[2] == {"role": "tool", "tool_call_id": "call_1",
                         "content": json.dumps({"order_id": "A-17", "status": "shipped"})}


@pytest.mark.parametrize("name,args,outcome", [
    ("get_order_status", '{"order":"A-17"}', "invalid_args"),
    ("delete_order", '{"order_id":"A-17"}', "unknown_tool"),
    ("get_order_status", '{"order_id":"boom"}', "tool_error"),
])
def test_tool_problems_go_back_to_the_model(name, args, outcome):
    seen, replies = [], iter([completion(None, "tool_calls", tool_calls=tool_call(name, args)), completion("Sorry.")])
    run = chat_api.run_with_tools(client_with(lambda r: next(replies), seen), [{"role": "user", "content": "x"}], TOOLS)
    assert run.calls == [(name, outcome)]
    sent = json.loads(json.loads(seen[1].content)["messages"][-1]["content"])
    assert "error" in sent and "database down" not in json.dumps(sent)


def test_step_limit_stops_a_looping_model():
    c = client_with(lambda r: completion(None, "tool_calls", tool_calls=tool_call("get_order_status", '{"order_id":"A"}')), [])
    run = chat_api.run_with_tools(c, [{"role": "user", "content": "x"}], TOOLS, max_steps=3)
    assert run.stopped == "step_limit" and run.answer is None and len(run.calls) == 3


class Ticket(BaseModel):
    category: str
    priority: int


def test_extract_ok_refused_truncated():
    ok = chat_api.extract(client_with(lambda r: completion('{"category":"billing","priority":2}'), seen := []),
                          Ticket, "Classify the ticket.", "I was charged twice")
    assert ok.status == "ok" and ok.value == Ticket(category="billing", priority=2)
    body = json.loads(seen[0].content)
    assert body["response_format"]["type"] == "json_schema" and body["response_format"]["json_schema"]["strict"] is True
    refused = chat_api.extract(client_with(lambda r: completion(None, refusal="I can't help with that."), []), Ticket, "s", "t")
    assert refused.status == "refused"
    cut = chat_api.extract(client_with(lambda r: completion('{"category":"bil', finish="length"), []), Ticket, "s", "t")
    assert cut.status == "truncated"


def sse(*events):
    body = "".join(f"data: {json.dumps(e)}\n\n" for e in events) + "data: [DONE]\n\n"
    return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body.encode())


def chunk(delta=None, finish=None, usage=None, choices=True):
    return {"id": "s1", "object": "chat.completion.chunk", "created": 1725958800, "model": chat_api.MODEL,
            "choices": [{"index": 0, "delta": delta or {}, "finish_reason": finish}] if choices else [],
            "usage": usage}


def test_stream_collects_text_and_usage():
    seen, got = [], []
    c = client_with(lambda r: sse(chunk({"role": "assistant", "content": ""}), chunk({"content": "Hel"}),
                                  chunk({"content": "lo"}), chunk(finish="stop"),
                                  chunk(choices=False, usage={"prompt_tokens": 9, "completion_tokens": 2,
                                                              "total_tokens": 11})), seen)
    out = chat_api.stream_text(c, [{"role": "user", "content": "hi"}], got.append)
    assert out.text == "Hello" and got == ["Hel", "lo"] and out.finish_reason == "stop"
    assert (out.prompt_tokens, out.completion_tokens) == (9, 2)
    assert json.loads(seen[0].content)["stream_options"] == {"include_usage": True}


def test_client_retries_429_then_succeeds():
    replies = iter([httpx.Response(429, headers={"retry-after-ms": "10"}, json={"error": {"message": "slow down"}}),
                    completion("ok")])
    seen = []
    c = client_with(lambda r: next(replies), seen, max_retries=2)
    assert c.chat.completions.create(model=chat_api.MODEL, messages=[{"role": "user", "content": "x"}]).choices[0].message.content == "ok"
    assert len(seen) == 2 and c.timeout == 60.0


def test_batch_lines_and_results():
    lines = list(chat_api.batch_lines({"t-1": [{"role": "user", "content": "a"}]}, temperature=0))
    rec = json.loads(lines[0])
    assert rec["custom_id"] == "t-1" and rec["url"] == "/v1/chat/completions" and rec["body"]["temperature"] == 0
    out = [
        json.dumps({"id": "r2", "custom_id": "t-2", "response": {"status_code": 400, "body": {"error": {"message": "bad"}}}, "error": None}),
        json.dumps({"id": "r1", "custom_id": "t-1", "response": {"status_code": 200, "body": {
            "choices": [{"message": {"role": "assistant", "content": "done"}}]}}, "error": None}),
    ]
    res = chat_api.read_batch_results(iter(out))
    assert res["t-1"] == {"ok": True, "content": "done"} and res["t-2"]["ok"] is False
