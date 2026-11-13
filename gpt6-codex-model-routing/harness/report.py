"""Summarises what the Codex CLI sent to the stand-in, and checks it. Usage: report.py <output dir>"""
import json
import pathlib
import sys

out = pathlib.Path(sys.argv[1])
runs: dict[str, list[dict]] = {}
for path in sorted(out.glob("requests-*.jsonl")):
    entries = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    requests = [entry for entry in entries if entry.get("request")]
    others = [f"{entry['method']} {entry['path']}" for entry in entries if not entry.get("request")]
    print(f"\n== {path.stem.removeprefix('requests-')}: {len(requests)} model requests" + (f"; other calls: {sorted(set(others))}" if others else ""))
    runs[path.stem.removeprefix("requests-")] = requests
    if not requests:
        continue
    first = requests[0]
    print(f"model {first['model']}, reasoning {first['reasoning']}, service_tier {first['service_tier']}, stream {first['stream']}, store {first['store']}, cache key sent {first['prompt_cache_key']}")
    print(f"top-level fields: {', '.join(first['top_level_keys'])}")
    print(f"include: {first['include']}; tool_choice {first['tool_choice']}; parallel_tool_calls {first['parallel_tool_calls']}")
    print(f"{len(first['tools'])} tools: " + ", ".join(f"{tool['name'] or tool['type']}({','.join(tool['parameters'])})" for tool in first["tools"]))
    if path.stem.endswith("default"):
        print("\n".join("   " + line[:230] for line in first.get("tool_outline", [])))
    for kind, keys, start in zip(first["item_kinds"], first["item_keys"], first["item_starts"]):
        print(f"   item {kind}: keys {keys}; starts {start}")
    models = sorted({(request["model"], json.dumps(request["reasoning"])) for request in requests})
    if len(models) > 1:
        print(f"models used in this run: {models}")
    print(f"{'request':>7} {'agent':>6} {'model':>12} {'effort':>7} {'reply':>8} {'tools':>7} {'input items':>12} {'input tokens':>13} {'prompt tokens':>14} {'earlier items unchanged':>24}")
    previous = {}
    for request in requests:
        before = previous.get(request["agent"])
        prefix = before is None or request["item_digests"][:len(before["item_digests"])] == before["item_digests"]
        print(f"{request['request']:>7} {request['agent']:>6} {request['model']:>12} {(request['reasoning'] or {}).get('effort', '-'):>7} {request['replied_with']:>8} {request['tools_tokens']:>7,} {request['input_items']:>12} {request['input_tokens']:>13,} {request['prompt_tokens']:>14,} {('-' if before is None else str(prefix)):>24}")
        previous[request["agent"]] = request
    last = requests[-1]
    print("items in the last request: " + ", ".join(f"{kind} {tokens:,}" for kind, tokens in zip(last["item_kinds"], last["item_tokens"])))
    print(f"same cache key on every request: {len({request['prompt_cache_key_digest'] for request in requests}) == 1}")


passed = total = 0


def check(what: str, ok: bool) -> None:
    global passed, total
    total += 1
    passed += ok
    print(f"{'ok  ' if ok else 'FAIL'}  {what}")


def sent(request: dict) -> tuple:
    return request["model"], (request["reasoning"] or {}).get("effort"), request["service_tier"]


print("\n== checks on what the CLI sent")
default = runs.get("default", [])
check("default configuration: seven requests, all to gpt-6-sol at medium effort", len(default) == 7 and {sent(r) for r in default} == {("gpt-6-sol", "medium", None)})
check("every request repeats the earlier items unchanged and adds exactly two: the call and its output",
      all(b["item_digests"][:len(a["item_digests"])] == a["item_digests"] and b["input_items"] == a["input_items"] + 2 for a, b in zip(default, default[1:])))
check("the tool declarations and the cache key are identical on all seven", len({(r["tools_digest"], r["prompt_cache_key_digest"]) for r in default}) == 1 and default[0]["prompt_cache_key"])
check("responses are not stored, and tools are declared in an input item, not a top-level field", all(r["store"] is False and "tools" not in r["top_level_keys"] and r["item_kinds"][0].startswith("additional_tools") for r in default))
check("--profile deep sends gpt-6-astra at high effort", {sent(r) for r in runs.get("deep", [])} == {("gpt-6-astra", "high", None)})
check("--profile ci sends gpt-6-sol at low effort on the flex tier", {sent(r) for r in runs.get("ci", [])} == {("gpt-6-sol", "low", "flex")})
subagent = [r for r in runs.get("subagent", []) if r["agent"] == "other"]
check("a spawned subagent's request goes to gpt-6-luna at low effort, as agents.default_subagent_model says", bool(subagent) and {sent(r) for r in subagent} == {("gpt-6-luna", "low", None)})
if subagent:
    print(f"      the subagent's first request carries {subagent[0]['prompt_tokens']:,} tokens before it has done anything")
check("codex exec review sends gpt-6-astra, the review_model", bool(runs.get("review")) and {r["model"] for r in runs["review"]} == {"gpt-6-astra"})
compact = runs.get("compact", [])
summaries = [i for i, r in enumerate(compact) if r["replied_with"] == "summary"]
check("with the limit at 20,000 tokens the CLI asks for a summary as soon as a reply reports more than that", bool(summaries) and all(compact[i - 1]["prompt_tokens"] > 20_000 for i in summaries))
if summaries:
    i = summaries[0]
    before, request, after = compact[i - 1], compact[i], compact[i + 1]
    check("the summary request carries no tool declarations, so it does not start like the request before it", request["tools_tokens"] < 10 and request["item_digests"][0] != before["item_digests"][0])
    leading = next((n for n, (x, y) in enumerate(zip(compact[0]["item_digests"], after["item_digests"])) if x != y), len(after["item_digests"]))
    same_tokens = sum(after["item_tokens"][:leading])
    check("the request after it is smaller than the one before the summary and begins with the same tool declarations and main instructions as the first request",
          leading >= 2 and after["prompt_tokens"] < before["prompt_tokens"])
    print(f"      before {before['prompt_tokens']:,} tokens, summary request {request['prompt_tokens']:,}, after {after['prompt_tokens']:,}")
    print(f"      after: the first {leading} items ({same_tokens:,} tokens) are byte-identical to the first request's; the other {len(after['item_digests']) - leading} are new or re-created")
    print(f"      after: {', '.join(f'{kind} {tokens:,}' for kind, tokens in zip(after['item_kinds'], after['item_tokens']))}")
legacy = (out / "codex-legacy.txt").read_text(encoding="utf-8") if (out / "codex-legacy.txt").exists() else ""
check("a [profiles.deep] table in config.toml makes --profile deep fail with a message that calls it legacy", "legacy" in legacy and not runs.get("legacy"))
print(f"\n{passed} of {total} checks passed")
sys.exit(0 if passed == total else 1)
