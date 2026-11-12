"""Checks the cost model against the figures quoted in the article."""
import math

from caching_economics import (BEDROCK_CLAUDE_1H, BEDROCK_CLAUDE_5M, azure_openai, break_even_gap_minutes,
                               break_even_hit_rate, hit_probability, relative_cost)

assert round(break_even_hit_rate(BEDROCK_CLAUDE_5M), 3) == 0.217
assert round(break_even_hit_rate(BEDROCK_CLAUDE_1H), 3) == 0.526
assert round(break_even_gap_minutes(BEDROCK_CLAUDE_5M), 1) == 20.4
assert round(break_even_gap_minutes(BEDROCK_CLAUDE_1H), 1) == 80.3
assert break_even_hit_rate(azure_openai(0.5)) == 0 and break_even_gap_minutes(azure_openai(0.5)) == math.inf
assert round(relative_cost(hit_probability(5, 5), BEDROCK_CLAUDE_5M), 2) == 0.52
assert round(relative_cost(hit_probability(60, 5), BEDROCK_CLAUDE_5M), 2) == 1.16
assert round(relative_cost(hit_probability(60, 60), BEDROCK_CLAUDE_1H), 2) == 0.80
assert round(24000 * relative_cost(hit_probability(60, 5), BEDROCK_CLAUDE_5M)) == 27793
print("MODEL TESTS OK")
