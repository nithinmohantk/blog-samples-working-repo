"""Print one simulated conversation and the judges' reasons.

  python tools/show.py results/simulation-v1.json identifier-pasted [max_chars]
"""
import json
import sys

from rxgate.checks import _text
from rxgate.gate import messages, scenario_id

path, wanted = sys.argv[1], sys.argv[2]
width = int(sys.argv[3]) if len(sys.argv) > 3 else 220
for item in json.load(open(path))["items"]:
    if scenario_id(item) != wanted:
        continue
    for m in messages(item):
        if m.get("role") in ("user", "assistant"):
            text = " ".join(_text(m.get("content")).split())
            if text:
                print(f"{m['role'][:4].upper()}: {text[:width]}")
    for r in item.get("results") or []:
        reason = ""
        for key in ("reason", "explanation"):
            reason = reason or (r.get(key) or (r.get("sample") or {}).get(key) or "")
        props = r.get("properties") or {}
        reason = reason or props.get("reason") or props.get("explanation") or ""
        print(f"-- {r.get('name')}: passed={r.get('passed')} score={r.get('score')} {str(reason)[:width]}")
