"""Summarises what the Codex CLI sent to the stand-in. Usage: report.py <output dir>"""
import json
import pathlib
import sys

out = pathlib.Path(sys.argv[1])
for path in sorted(out.glob("requests-*.jsonl")):
    entries = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    requests = [entry for entry in entries if entry.get("request")]
    others = [f"{entry['method']} {entry['path']}" for entry in entries if not entry.get("request")]
    print(f"\n== {path.stem.removeprefix('requests-')}: {len(requests)} model requests" + (f"; other calls: {sorted(set(others))}" if others else ""))
    if not requests:
        continue
    first = requests[0]
    print(f"model {first['model']}, reasoning {first['reasoning']}, service_tier {first['service_tier']}, stream {first['stream']}, store {first['store']}, cache key sent {first['prompt_cache_key']}")
    print(f"top-level fields: {', '.join(first['top_level_keys'])}")
    print(f"include: {first['include']}; tool_choice {first['tool_choice']}; parallel_tool_calls {first['parallel_tool_calls']}")
    print(f"{len(first['tools'])} tools: " + ", ".join(f"{tool['name'] or tool['type']}({','.join(tool['parameters'])})" for tool in first["tools"]))
    for kind, keys, start in zip(first["item_kinds"], first["item_keys"], first["item_starts"]):
        print(f"   item {kind}: keys {keys}; starts {start}")
    models = sorted({(request["model"], json.dumps(request["reasoning"])) for request in requests})
    if len(models) > 1:
        print(f"models used in this run: {models}")
    print(f"{'request':>7} {'instructions':>13} {'tools':>7} {'input items':>12} {'input tokens':>13} {'prompt tokens':>14} {'same instructions and tools':>28} {'earlier items unchanged':>24}")
    previous = None
    for request in requests:
        stable = previous is None or (request["instructions_digest"], request["tools_digest"]) == (previous["instructions_digest"], previous["tools_digest"])
        prefix = previous is None or request["item_digests"][:len(previous["item_digests"])] == previous["item_digests"]
        print(f"{request['request']:>7} {request['instructions_tokens']:>13,} {request['tools_tokens']:>7,} {request['input_items']:>12} {request['input_tokens']:>13,} {request['prompt_tokens']:>14,} {str(stable):>28} {str(prefix):>24}")
        previous = request
    last = requests[-1]
    print("items in the last request: " + ", ".join(f"{kind} {tokens:,}" for kind, tokens in zip(last["item_kinds"], last["item_tokens"])))
    print(f"same cache key on every request: {len({request['prompt_cache_key_digest'] for request in requests}) == 1}")
