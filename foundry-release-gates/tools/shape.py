"""Print the shape of a results JSON file: keys, list lengths and short string prefixes.

  python tools/shape.py results/simulation-v1.json items.0
"""
import json
import sys


def shape(o, width=48):
    if isinstance(o, dict):
        return {k: shape(v, width) for k, v in o.items()}
    if isinstance(o, list):
        return [shape(o[0], width), f"... {len(o)} items"] if o else []
    if isinstance(o, str):
        return o[:width]
    return o


data = json.load(open(sys.argv[1]))
for part in (sys.argv[2].split(".") if len(sys.argv) > 2 else []):
    data = data[int(part)] if isinstance(data, list) else data[part]
print(json.dumps(shape(data), indent=1)[: int(sys.argv[3]) if len(sys.argv) > 3 else 6000])
