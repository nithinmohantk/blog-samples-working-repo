"""List flagged turns of a saved run as override stubs for a reviewer to complete.

  PYTHONPATH=. python tools/flagged.py 3 > /tmp/stubs.json

Nothing is overridden until a person fills in reason and reviewer and copies
the entry into overrides.json. Identifier leaks are never listed.
"""
import json
import sys

from rxgate.foundry import RESULTS
from rxgate.gate import summarise

version = sys.argv[1]
items = json.loads((RESULTS / f"simulation-v{version}.json").read_text())["items"]
result, _ = summarise(version, items)
stubs = [
    {"version": version, "scenario": f.scenario, "conversation": f.conversation, "rule": f.rule,
     "detail": f.detail, "reason": "", "reviewer": ""}
    for f in result.failures if f.rule != "identifier_leak"
]
print(json.dumps(stubs, indent=2))
