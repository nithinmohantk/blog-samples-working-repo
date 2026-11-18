"""Convert three Claude 2 Text Completions requests and price one workload on four models.

    python tools/demo.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from claude_migrate.cost import PRICES, monthly  # noqa: E402
from claude_migrate.legacy import PromptFormatError, convert_body  # noqa: E402

REQUESTS = {
    "summary with a system prompt": {
        "prompt": "You summarise clinical notes in one sentence. Never add facts.\n\nHuman: <note>Admitted with chest "
                  "pain. Troponin negative twice. Discharged day 3 on aspirin.</note>\n\nAssistant:",
        "max_tokens_to_sample": 200, "stop_sequences": ["\n\nHuman:"], "temperature": 0.0},
    "JSON with a prefill": {
        "prompt": "\n\nHuman: Extract the medication names from: aspirin 75 mg, atorvastatin 40 mg.\n\nAssistant: {\"medications\": [",
        "max_tokens_to_sample": 100, "stop_sequences": ["\n\nHuman:", "]}"]},
    "prompt with no Human turn": {
        "prompt": "Summarise this: aspirin 75 mg daily.", "max_tokens_to_sample": 100},
}

for name, old in REQUESTS.items():
    print(f"== {name}")
    print("Text Completions body:")
    print(json.dumps(old, indent=2))
    try:
        print("Messages body:")
        print(json.dumps(convert_body(old), indent=2))
    except PromptFormatError as err:
        print(f"  refused: {err}")
    print()

INPUT, OUTPUT = 50_000_000, 10_000_000
print(f"== One month: {INPUT:,} input and {OUTPUT:,} output tokens, on-demand, US East (N. Virginia)")
for model in PRICES:
    print(f"  {model:<20} ${monthly(model, INPUT, OUTPUT):>10,}")
