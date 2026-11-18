"""Every check in one script. Usage: python tests/run.py <output folder> <codex config schema.json>

Part 1 to 4 are arithmetic on the published prices. Part 5 validates the example Codex configuration against
the JSON schema that ships in the Codex repository. No model is called and the Codex CLI is not run.
"""
from __future__ import annotations

import copy
import json
import pathlib
import sys
import tomllib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import jsonschema

from gpt6_cost.model import PriceList, agent_session, write_share_break_even

here = pathlib.Path(__file__).resolve().parent.parent
out = pathlib.Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
prices = PriceList.load(here / "prices.json")
MODELS = ["gpt-6-astra", "gpt-6-sol", "gpt-6-luna"]
passed = total = 0
results: dict = {}


def check(what: str, ok: bool) -> None:
    global passed, total
    total += 1
    passed += ok
    print(f"{'ok  ' if ok else 'FAIL'}  {what}")


def close(a: float, b: float, tolerance: float = 0.005) -> bool:
    return abs(a - b) < tolerance


print("== 1. One request: 100,000 tokens in, 5,000 out")
print(f"{'model':13} {'no caching':>11} {'cache written':>14} {'cache read':>11}")
single = {}
for model in MODELS:
    plain = prices.request(model, 100_000, 0, 0, 5_000)
    written = prices.request(model, 0, 0, 100_000, 5_000)
    read = prices.request(model, 0, 100_000, 0, 5_000)
    single[model] = [round(plain, 4), round(written, 4), round(read, 4)]
    print(f"{model:13} {plain:>10.4f}$ {written:>13.4f}$ {read:>10.4f}$")
results["single_request"] = single
check("Astra: $1.25 plain, $1.50 when the prompt is written to the cache, $0.35 when it is read from it",
      close(single["gpt-6-astra"][0], 1.25) and close(single["gpt-6-astra"][1], 1.50) and close(single["gpt-6-astra"][2], 0.35))
check("Sol is a fifth of Astra and Luna a hundredth, on every line",
      all(close(single["gpt-6-sol"][i] * 5, single["gpt-6-astra"][i]) and close(single["gpt-6-luna"][i] * 100, single["gpt-6-astra"][i]) for i in range(3)))
share = write_share_break_even(prices.models["gpt-6-sol"])
print(f"caching stops paying when more than {share:.1%} of prompt tokens are writes; the same for all three models")
check("the break-even share of writes is 78.3% for every model", all(close(write_share_break_even(prices.models[m]), 0.7826, 0.0001) for m in MODELS))
twice_cached = prices.request("gpt-6-sol", 0, 0, 200_000, 0) + prices.request("gpt-6-sol", 0, 200_000, 0, 0)
twice_plain = 2 * prices.request("gpt-6-sol", 200_000, 0, 0, 0)
check("200,000 tokens on Sol, written once and read once, cost $0.54; sent twice without caching they cost $0.80", close(twice_cached, 0.54) and close(twice_plain, 0.80))

print("\n== 2. The step at 272,000 input tokens")
below = prices.request("gpt-6-sol", 0, 262_000, 10_000, 4_000)
above = prices.request("gpt-6-sol", 0, 263_000, 10_000, 4_000)
print(f"gpt-6-sol, 272,000 tokens in (262,000 read, 10,000 written), 4,000 out   ${below:.4f}")
print(f"gpt-6-sol, 273,000 tokens in (263,000 read, 10,000 written), 4,000 out   ${above:.4f}")
check("one thousand more tokens of context takes the request from $0.1174 to $0.2152", close(below, 0.1174, 0.00005) and close(above, 0.2152, 0.00005))
results["step"] = {"below": round(below, 4), "above": round(above, 4)}

print("\n== 3. An agent session: 30,000-token base, 60 steps, 5,000 tokens of tool output and 1,000 of output per step")
shape = dict(base=30_000, added_per_turn=5_000, output_per_turn=1_000, turns=60)
print(f"{'model':13} {'no caching':>11} {'cached':>9} {'cached, compact at 240,000':>27} {'largest context':>16} {'steps over 272,000':>19}")
sessions = {}
for model in MODELS:
    plain = agent_session(prices, model, caching=False, **shape)
    cached = agent_session(prices, model, **shape)
    compacted = agent_session(prices, model, compact_at=240_000, **shape)
    sessions[model] = {"no_caching": round(plain.cost, 2), "cached": round(cached.cost, 2), "compacted": round(compacted.cost, 2),
                       "largest_context": cached.largest_context, "steps_over": cached.turns_over, "compactions": compacted.compactions}
    print(f"{model:13} {plain.cost:>10.2f}$ {cached.cost:>8.2f}$ {compacted.cost:>26.2f}$ {cached.largest_context:>16,} {cached.turns_over:>19}")
results["sessions"] = sessions
sol = agent_session(prices, "gpt-6-sol", **shape)
check("the context grows by 6,000 tokens a step: 35,000 at step 1 and 389,000 at step 60", sol.turns[0].context == 35_000 and sol.turns[-1].context == 389_000)
check("step 2 reads the 35,000 tokens step 1 sent and writes the 6,000 that are new", (sol.turns[1].read, sol.turns[1].written) == (35_000, 6_000))
check("step 1 on Sol costs 35,000 written tokens and 1,000 of output: $0.0975", close(sol.turns[0].cost, 0.0975, 0.00005))
check("the first step over 272,000 tokens is step 41, and it costs about twice step 40",
      sol.turns[39].context == 269_000 and sol.turns[40].context == 275_000 and 1.9 < sol.turns[40].cost / sol.turns[39].cost < 2.1)
compacted = agent_session(prices, "gpt-6-sol", compact_at=240_000, **shape)
check("compacting at 240,000 keeps every request under the step and happens once in 60 steps", compacted.largest_context <= 240_000 and compacted.turns_over == 0 and compacted.compactions == 1)
check("for each model: caching beats no caching, and compaction beats running through the step",
      all(sessions[m]["compacted"] < sessions[m]["cached"] < sessions[m]["no_caching"] for m in MODELS))

print("\n== 4. One piece of work split across models")
# A feature: one planning session, six worker sessions, one review. The token counts are the same whichever model runs a part.
plan = dict(base=30_000, added_per_turn=4_000, output_per_turn=1_500, turns=10)
work = dict(base=30_000, added_per_turn=5_000, output_per_turn=1_000, turns=25)
review = dict(base=30_000, added_per_turn=20_000, output_per_turn=2_000, turns=5)


def feature(planner: str, worker: str, reviewer: str) -> float:
    return (agent_session(prices, planner, **plan).cost + 6 * agent_session(prices, worker, **work).cost
            + agent_session(prices, reviewer, **review).cost)


routes = {
    "everything on Astra": feature("gpt-6-astra", "gpt-6-astra", "gpt-6-astra"),
    "everything on Sol": feature("gpt-6-sol", "gpt-6-sol", "gpt-6-sol"),
    "Sol plans, Luna works, Astra reviews": feature("gpt-6-sol", "gpt-6-luna", "gpt-6-astra"),
    "Sol plans and reviews, Luna works": feature("gpt-6-sol", "gpt-6-luna", "gpt-6-sol"),
    "everything on Luna": feature("gpt-6-luna", "gpt-6-luna", "gpt-6-luna"),
}
for name, cost in routes.items():
    print(f"{name:38} ${cost:>7.2f}")
results["routes"] = {name: round(cost, 2) for name, cost in routes.items()}
check("all-Sol is a fifth of all-Astra, and all-Luna a hundredth", close(routes["everything on Sol"] * 5, routes["everything on Astra"]) and close(routes["everything on Luna"] * 100, routes["everything on Astra"]))
mixed = routes["Sol plans, Luna works, Astra reviews"]
review_cost = agent_session(prices, "gpt-6-astra", **review).cost
check(f"in the mixed route the Astra review is {review_cost / mixed:.0%} of the bill, more than the planning and the six workers together", review_cost > mixed / 2)

print("\n== 5. The example Codex configuration against the schema in the Codex repository")
schema = json.loads(pathlib.Path(sys.argv[2]).read_text(encoding="utf-8"))
config = tomllib.loads((here / "codex" / "config.toml").read_text(encoding="utf-8"))
validator = jsonschema.Draft7Validator(schema)
errors = [f"{'/'.join(map(str, error.path))}: {error.message}" for error in validator.iter_errors(config)]
for error in errors:
    print("  " + error)
check(f"config.toml is valid: {len(config)} top-level settings", not errors)
for name in ("deep", "bulk", "ci"):
    profile = tomllib.loads((here / "codex" / f"{name}.config.toml").read_text(encoding="utf-8"))
    check(f"{name}.config.toml is valid", not list(validator.iter_errors(profile)))


def broken(change) -> bool:
    candidate = copy.deepcopy(config)
    change(candidate)
    return any(True for _ in validator.iter_errors(candidate))


check("the schema rejects a misspelt key in the agents table's sibling settings: a sandbox mode that does not exist", broken(lambda c: c.update(sandbox_mode="workspace")))
check("and a compaction limit given as text", broken(lambda c: c.update(model_auto_compact_token_limit="240k")))
legacy = {**config, "profiles": {"deep": {"model": "gpt-6-astra"}}}
check("the schema still accepts a [profiles.deep] table, which this CLI version refuses to use with --profile: validation is not enough", not list(validator.iter_errors(legacy)))
check("the compaction limit in the file is below the 272,000-token price step", config["model_auto_compact_token_limit"] < prices.long_context_over)
described = schema["properties"]["model_auto_compact_token_limit"]["description"]
print(f"  schema, model_auto_compact_token_limit: {described}")
print(f"  schema, agents.default_subagent_model: {schema['definitions']['AgentsToml']['properties']['default_subagent_model']['description']}")
print(f"  schema, review_model: {schema['properties']['review_model']['description']}")

print(f"\n{passed} of {total} checks passed")
results["checks"] = {"passed": passed, "total": total}
(out / "results.json").write_text(json.dumps(results, indent=1) + "\n", encoding="utf-8")
sys.exit(0 if passed == total else 1)
