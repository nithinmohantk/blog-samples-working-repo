"""Every check in one script. Usage: python tests/run.py <output folder>

Part 1 counts a real repository (this samples repository) with tiktoken. Part 2 is arithmetic on the published
prices. Part 3 runs the client, through the official openai package, against the local stand-in.
No request leaves the machine and no model is involved.
"""
from __future__ import annotations

import json
import pathlib
import struct
import sys
import zlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import openai
import tiktoken
from openai import OpenAI

from codex_budget.budget import Prices, cacheable, count_repository, room_for_output, session_cost
from codex_budget.client import DoesNotFit, RepositorySession
from standin.server import IMAGE_TOKENS, StandIn

here = pathlib.Path(__file__).resolve().parent.parent
out = pathlib.Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
prices = Prices.load(here / "prices.json")
encoder = tiktoken.get_encoding("o200k_base")
passed = total = 0
results: dict = {}


def check(what: str, ok: bool) -> None:
    global passed, total
    total += 1
    passed += ok
    print(f"{'ok  ' if ok else 'FAIL'}  {what}")


def close(a: float, b: float) -> bool:
    return abs(a - b) < 0.005


print(f"openai {openai.__version__}, tiktoken {tiktoken.__version__}; tiktoken maps gpt-5 to {tiktoken.encoding_for_model('gpt-5').name}")

print("\n== 1. How much code is 400,000 tokens?")
repository = here.parent
print(f"{'language':12} {'files':>6} {'lines':>8} {'tokens':>10} {'tokens per line':>16} {'lines in 400,000 tokens':>24}")
by_language = {"C#": (".cs",), "Python": (".py",), "TypeScript": (".ts", ".tsx"), "Terraform": (".tf", ".hcl"), "all four": (".cs", ".py", ".ts", ".tsx", ".tf", ".hcl")}
for language, suffixes in by_language.items():
    count = count_repository(repository, suffixes, encoder)
    if count.files:
        print(f"{language:12} {count.files:>6,} {count.lines:>8,} {count.tokens:>10,} {count.tokens_per_line:>16.1f} {prices.context_window / count.tokens_per_line:>24,.0f}")
        results[language] = {"files": count.files, "lines": count.lines, "tokens": count.tokens, "tokens_per_line": round(count.tokens_per_line, 1)}
everything = count_repository(repository, by_language["all four"], encoder)
check("the count is repeatable: a second pass over the same files gives the same number", everything == count_repository(repository, by_language["all four"], encoder))

print("\n== 2. What the published prices imply")
full = prices.cost(prices.context_window, 0, 0)
print(f"400,000 input tokens, none cached      ${full:.2f}")
print(f"400,000 input tokens, all cached       ${prices.cost(prices.context_window, prices.context_window, 0):.2f}")
print(f"16,000 output tokens                   ${prices.cost(0, 0, 16_000):.2f}")
check("a full window of input is $0.70, and $0.07 when all of it is cached", close(full, 0.70) and close(prices.cost(400_000, 400_000, 0), 0.07))
check("cached input is one tenth of the input price", abs(prices.cached_input / prices.input - 0.1) < 1e-9)
check("the cacheable part of a prefix is 0 below 1,024 tokens and moves in steps of 128 above it",
      (cacheable(1023), cacheable(1024), cacheable(1151), cacheable(1152), cacheable(250_000)) == (0, 1024, 1024, 1152, 249_984))
check("a 250,000-token repository and a 500-token question leave 149,500 tokens for reasoning and the answer",
      room_for_output(prices, 250_000, 500) == 149_500)
print(f"\n{'repository':>12} {'questions':>10} {'no caching':>12} {'cache warm':>12} {'saving':>8}")
table = []
for prefix in (50_000, 150_000, 250_000):
    for questions in (1, 10, 40):
        session = session_cost(prices, prefix, question_tokens=500, output_tokens=4_000, questions=questions)
        print(f"{prefix:>12,} {questions:>10} {session.without_cache:>11.2f}$ {session.with_cache:>11.2f}$ {session.saving:>8.0%}")
        table.append({"prefix": prefix, "questions": questions, "without": round(session.without_cache, 2), "with": round(session.with_cache, 2), "saving": round(session.saving, 3)})
results["sessions"] = table
ten = session_cost(prices, 250_000, 500, 4_000, 10)
check("ten questions about a 250,000-token repository: $4.94 without caching, $1.40 with a warm cache", close(ten.without_cache, 4.94) and close(ten.with_cache, 1.40))

print("\n== 3. The client against the local stand-in")
files = {str(path.relative_to(repository)): path.read_text(encoding="utf-8") for path in sorted((repository / "smart-backend-services").rglob("*.cs"))}
stand_in = StandIn(encoder, fail_first_with_429=True)
client = OpenAI(base_url=stand_in.base_url, api_key="not-a-real-key", max_retries=2)
session = RepositorySession(client, "gpt-5.2-codex", prices, encoder, files, max_output_tokens=16_000)
print(f"{len(files)} C# files, {session.prefix_tokens:,} tokens of instructions and repository")

first = session.ask("Where is the client assertion's audience checked?")
check("the first request is retried after a 429 and then answered", first.text == "stand-in answer" and len(stand_in.requests) == 1)
check("nothing is cached on the first request", first.cached_tokens == 0)
second = session.ask("Which checks run before the jti is recorded?")
check(f"a different question about the same repository is served {second.cached_tokens:,} cached tokens: the whole prefix, to the nearest step of 128",
      cacheable(session.prefix_tokens) <= second.cached_tokens <= session.prefix_tokens + 8)
check("the second request costs less than a fifth of the first", second.cost < first.cost / 5)
print(f"  first request  {first.input_tokens:,} input, {first.cached_tokens:,} cached, ${first.cost:.4f}")
print(f"  second request {second.input_tokens:,} input, {second.cached_tokens:,} cached, ${second.cost:.4f}")
results["stand_in"] = {"prefix_tokens": session.prefix_tokens, "first_cost": round(first.cost, 4), "second_cost": round(second.cost, 4), "second_cached": second.cached_tokens}

body = stand_in.requests[-1]
check("the request puts the repository before the question, sets a cache key and does not store the response",
      body["input"][0]["content"][0]["text"].startswith("### FILE") and body["input"][1]["content"][0]["text"].startswith("Which checks")
      and body["prompt_cache_key"].startswith("repo-") and body["store"] is False and body["reasoning"] == {"effort": "medium"})

# A 1x1 PNG, built here so that the repository holds no binary file.
png = out / "pixel.png"
raw = b"\x00\xff\xff\xff"
chunk = lambda kind, data: struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
png.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
third = session.ask("Does the code match this diagram?", image=png)
sent = stand_in.requests[-1]["input"][1]["content"]
check("an image is sent after the question as a data URL, and the repository is still served from the cache",
      sent[1]["type"] == "input_image" and sent[1]["image_url"].startswith("data:image/png;base64,") and third.cached_tokens == second.cached_tokens
      and third.input_tokens > second.input_tokens + IMAGE_TOKENS - 50)

# The mistake to avoid: anything that changes placed before the repository.
moved = client.responses.create(model="gpt-5.2-codex", instructions="Today is Monday. " + body["instructions"], input=body["input"], prompt_cache_key=body["prompt_cache_key"], max_output_tokens=16_000)
check("one changed sentence in front of the repository and nothing is cached", moved.usage.input_tokens_details.cached_tokens == 0)

other = RepositorySession(client, "gpt-5.2-codex", prices, encoder, {**files, "NEW.cs": "// a new file\n"}, max_output_tokens=16_000)
changed = other.ask("Which checks run before the jti is recorded?")
check("a new snapshot of the repository has its own cache key and starts cold", changed.cached_tokens == 0 and stand_in.requests[-1]["prompt_cache_key"] != body["prompt_cache_key"])

big = RepositorySession(client, "gpt-5.2-codex", prices, encoder, {"big.txt": "word " * 390_000}, max_output_tokens=16_000)
before = len(stand_in.requests)
try:
    big.ask("Summarise.")
    refused = False
except DoesNotFit as error:
    refused = True
    print(f"  refused locally: {error}")
check("a repository that leaves no room for the answer is refused before any request is sent", refused and len(stand_in.requests) == before)

token_client = OpenAI(base_url=stand_in.base_url, api_key=lambda: "token-from-a-provider", max_retries=0)
RepositorySession(token_client, "my-deployment", prices, encoder, files).ask("Anything?")
check("a token provider in place of a key reaches the server as a bearer token, as Entra ID sign-in to Foundry needs",
      stand_in.authorizations[-1] == "Bearer token-from-a-provider" and stand_in.requests[-1]["model"] == "my-deployment")
stand_in.close()

print(f"\n{passed} of {total} checks passed")
results["checks"] = {"passed": passed, "total": total}
png.unlink()
(out / "results.json").write_text(json.dumps(results, indent=1) + "\n", encoding="utf-8")
sys.exit(0 if passed == total else 1)
