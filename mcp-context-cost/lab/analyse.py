"""Turn the collected tool listings into the numbers in the article.

    python lab/analyse.py <directory holding listings.json>
"""
from __future__ import annotations

import json
import random
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from measure.search import LOAD_TOOL, SEARCH_TOOL, ToolIndex, catalogue  # noqa: E402
from measure.slim import LEVELS  # noqa: E402
from measure.tokens import PRIMARY, SECONDARY, count, listing_cost, tool_cost  # noqa: E402

SETUPS = {
    "coding agent": ["filesystem", "git", "github", "playwright"],
    "coding agent, all GitHub toolsets": ["filesystem", "git", "github-all-toolsets", "playwright"],
    "research assistant": ["fetch", "memory", "time", "sequential-thinking"],
    "everything connected": None,  # every distinct server that started
}
SUBSETS = {"github"}  # the default GitHub toolsets are part of github-all-toolsets; never count both
WINDOWS = (128_000, 200_000, 1_000_000)
TURNS = 30  # model requests in one working session; every request carries the tool definitions again


def inventory(servers: list[dict]) -> list[dict]:
    rows = []
    print(f"{'server':<20} {'tools':>5} {'tokens':>8} {'cl100k':>8} {'chars':>8} {'median':>7} {'largest':>8}  {'description':>11} {'schema':>7}")
    for server in servers:
        costs = [tool_cost(tool) for tool in server["tools"]]
        total = listing_cost(server["tools"])
        described, schema = sum(c["description"] for c in costs), sum(c["schema"] for c in costs)
        row = {"server": server["name"], "version": server["version"], "tools": len(costs), "tokens": total,
               "tokens_cl100k": listing_cost(server["tools"], SECONDARY), "characters": sum(c["characters"] for c in costs),
               "median_per_tool": int(statistics.median(c["total"] for c in costs)), "largest_tool": max(c["total"] for c in costs),
               "description_share": round(described / (described + schema), 2), "instructions_tokens": count(server.get("instructions", ""))}
        rows.append(row)
        print(f"{row['server']:<20} {row['tools']:>5} {row['tokens']:>8,} {row['tokens_cl100k']:>8,} {row['characters']:>8,} {row['median_per_tool']:>7} "
              f"{row['largest_tool']:>8,}  {row['description_share']:>10.0%} {1 - row['description_share']:>7.0%}")
    distinct = [r for r in rows if r["server"] not in SUBSETS]
    print(f"{'all distinct':<20} {sum(r['tools'] for r in distinct):>5} {sum(r['tokens'] for r in distinct):>8,} {sum(r['tokens_cl100k'] for r in distinct):>8,}")
    return rows


def largest(servers: list[dict], limit: int = 10) -> list[dict]:
    tools = [{"server": s["name"], "tool": t["name"], **tool_cost(t)} for s in servers for t in s["tools"]]
    tools.sort(key=lambda t: -t["total"])
    print(f"\n{'largest definitions':<44} {'tokens':>7} {'description':>12} {'schema':>7}")
    for tool in tools[:limit]:
        print(f"{tool['server'] + '.' + tool['tool']:<44} {tool['total']:>7,} {tool['description']:>12,} {tool['schema']:>7,}")
    under = sum(1 for t in tools if t["total"] < 100)
    print(f"{under} of {len(tools)} definitions are under 100 tokens; the largest {limit} hold "
          f"{sum(t['total'] for t in tools[:limit]) / sum(t['total'] for t in tools):.0%} of all tokens")
    return tools[:limit]


def setups(servers: list[dict]) -> list[dict]:
    by_name = {s["name"]: s for s in servers}
    rows = []
    print(f"\n{'setup':<34} {'servers':>7} {'tools':>5} {'tokens':>8}  " + "  ".join(f"{w // 1000:>4}k window" for w in WINDOWS) + f"  over {TURNS} requests")
    for name, members in SETUPS.items():
        chosen = [by_name[m] for m in (members or [n for n in by_name if n not in SUBSETS]) if m in by_name]
        tools = [t for s in chosen for t in s["tools"]]
        tokens = listing_cost(tools)
        rows.append({"setup": name, "servers": [s["name"] for s in chosen], "tools": len(tools), "tokens": tokens,
                     "share_of_window": {str(w): round(tokens / w, 4) for w in WINDOWS}, "tokens_over_session": tokens * TURNS})
        print(f"{name:<34} {len(chosen):>7} {len(tools):>5} {tokens:>8,}  " + "  ".join(f"{tokens / w:>11.1%}" for w in WINDOWS) + f"  {tokens * TURNS:>12,}")
    return rows


def slimming(servers: list[dict]) -> list[dict]:
    tools = [t for s in servers for t in s["tools"]]
    before = listing_cost(tools)
    rows = [{"level": "0 as published", "tokens": before, "saved": 0.0}]
    print(f"\n{'reduction':<32} {'tokens':>8} {'saved':>7}   by server")
    print(f"{'0 as published':<32} {before:>8,} {'':>7}")
    for label, transform in LEVELS.items():
        after = listing_cost([transform(t) for t in tools])
        per_server = {s["name"]: round(1 - listing_cost([transform(t) for t in s["tools"]]) / listing_cost(s["tools"]), 2) for s in servers}
        rows.append({"level": label, "tokens": after, "saved": round(1 - after / before, 3), "by_server": per_server})
        print(f"{label:<32} {after:>8,} {1 - after / before:>7.1%}   " + ", ".join(f"{name} {share:.0%}" for name, share in per_server.items()))
    return rows


def retrieval(servers: list[dict], tasks: list[dict]) -> dict:
    tools = [{**t, "server": s["name"]} for s in servers for t in s["tools"]]
    index = ToolIndex(tools)
    known = {(t["server"], t["name"]) for t in tools}
    usable = [task for task in tasks if (task["server"], task["tool"]) in known]
    ranks = []
    for task in usable:
        found = [(t["server"], t["name"]) for t in index.search(task["query"], 10)]
        ranks.append(found.index((task["server"], task["tool"])) + 1 if (task["server"], task["tool"]) in found else None)
    hit = {k: sum(1 for r in ranks if r and r <= k) for k in (1, 3, 5, 10)}
    print(f"\ntool search over {len(tools)} tools, {len(usable)} written tasks ({len(tasks) - len(usable)} skipped: tool not in these listings)")
    print("  expected tool ranked first: {0} | in the top 3: {1} | in the top 5: {2} | in the top 10: {3} | not found: {4}".format(
        hit[1], hit[3], hit[5], hit[10], sum(1 for r in ranks if r is None)))
    for task, rank in zip(usable, ranks):
        if rank is None or rank > 5:
            print(f"  rank {rank or 'none':<5} {task['server']}.{task['tool']:<28} {task['query']}")
    return {"tasks": len(usable), "skipped": len(tasks) - len(usable), "hit": hit, "ranks": ranks, "index": index, "usable": usable, "tools": tools}


def sessions(found: dict, runs: int = 1000, seed: int = 20260305) -> list[dict]:
    """Simulated sessions: each uses a few distinct tools, found through search and kept loaded afterwards."""
    index, usable, tools = found["index"], found["usable"], found["tools"]
    everything = listing_cost(tools)
    search_tool = tool_cost(SEARCH_TOOL)["total"]
    cost = {(t["server"], t["name"]): tool_cost(t)["total"] for t in tools}
    rng, rows = random.Random(seed), []
    print(f"\nall {len(tools)} definitions up front: {everything:,} tokens per request; the search tool alone: {search_tool} tokens")
    print(f"{'distinct tools used':>19} {'up front':>12} {'deferred':>12} {'saved':>7} {'loaded at end':>14} {'widened':>8} {'failed':>7}")
    for used in (2, 4, 8):
        totals, loaded_end, widened, failed = [], [], 0, 0
        for _ in range(runs):
            chosen = rng.sample(usable, used)
            when = sorted(rng.sample(range(TURNS), used))  # the request at which each tool is first needed
            loaded: set[tuple[str, str]] = set()
            total, wide, lost = 0, False, False
            for request in range(TURNS):
                for task, at in zip(chosen, when):
                    if at == request:
                        target = (task["server"], task["tool"])
                        results = [(t["server"], t["name"]) for t in index.search(task["query"], 10)]
                        loaded.update(results[:5])
                        total += count(task["query"])  # the search call itself
                        if target not in results[:5]:
                            wide = True
                            loaded.update(results[5:10])  # the model asks again for more
                            total += count(task["query"])
                            if target not in results:
                                lost = True
                total += search_tool + sum(cost[key] for key in loaded)
            totals.append(total)
            loaded_end.append(len(loaded))
            widened += wide
            failed += lost
        row = {"distinct_tools": used, "up_front": everything * TURNS, "deferred_mean": int(statistics.mean(totals)),
               "saved": round(1 - statistics.mean(totals) / (everything * TURNS), 3), "loaded_at_end_mean": round(statistics.mean(loaded_end), 1),
               "sessions_widened": round(widened / runs, 3), "sessions_failed": round(failed / runs, 3)}
        rows.append(row)
        print(f"{used:>19} {row['up_front']:>12,} {row['deferred_mean']:>12,} {row['saved']:>7.1%} {row['loaded_at_end_mean']:>14} "
              f"{row['sessions_widened']:>8.1%} {row['sessions_failed']:>7.1%}")
    return rows


def catalogues(found: dict, runs: int = 1000, seed: int = 20260305) -> list[dict]:
    """The other way to defer: keep a short catalogue of every tool in the prompt and load definitions by exact name."""
    usable, tools = found["usable"], found["tools"]
    everything = listing_cost(tools)
    loader = tool_cost(LOAD_TOOL)["total"]
    cost = {(t["server"], t["name"]): tool_cost(t)["total"] for t in tools}
    rows = []
    print(f"\n{'catalogue kept in the prompt':<36} {'tokens':>7}   mean tokens over {TURNS} requests, by distinct tools used (2, 4, 8), and saving")
    for label, with_summary in (("names only", False), ("names and first sentence", True)):
        listed = count(catalogue(tools, with_summary))
        rng, cells = random.Random(seed), []
        for used in (2, 4, 8):
            totals = []
            for _ in range(runs):
                chosen = rng.sample(usable, used)
                when = sorted(rng.sample(range(TURNS), used))
                total = sum(loader + listed + sum(cost[(task["server"], task["tool"])] for task, at in zip(chosen, when) if at <= request)
                            for request in range(TURNS))
                totals.append(total)
            cells.append({"distinct_tools": used, "mean": int(statistics.mean(totals)), "saved": round(1 - statistics.mean(totals) / (everything * TURNS), 3)})
        rows.append({"catalogue": label, "tokens": listed, "sessions": cells})
        print(f"{label:<36} {listed:>7,}   " + "   ".join(f"{c['mean']:>9,} ({c['saved']:.1%})" for c in cells))
    return rows


def main(directory: str) -> int:
    collected = json.loads(Path(directory, "listings.json").read_text(encoding="utf-8"))
    servers = [server for server in collected if server["tools"]]
    print(f"tokeniser {PRIMARY} (second column {SECONDARY}); {len(servers)} servers, {sum(len(s['tools']) for s in servers)} tools\n")
    distinct = [server for server in servers if server["name"] not in SUBSETS]
    report = {"inventory": inventory(servers), "largest": largest(distinct), "setups": setups(servers), "slimming": slimming(distinct)}
    tasks = json.loads((HERE.parent / "tasks.json").read_text(encoding="utf-8"))["tasks"]
    found = retrieval(distinct, tasks)
    report["retrieval"] = {key: found[key] for key in ("tasks", "skipped", "hit", "ranks")}
    report["sessions"] = sessions(found)
    report["catalogues"] = catalogues(found)
    Path(directory, "context-cost.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
