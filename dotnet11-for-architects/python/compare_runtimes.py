"""Compare two UpgradeCheck reports: python compare_runtimes.py net10.json net11.json"""
import json
import sys

old, new = (json.load(open(path, encoding="utf-8")) for path in sys.argv[1:3])
print(f"{old['runtime']}  ->  {new['runtime']}\n")
changed = [key for key in old["behaviour"] if old["behaviour"][key] != new["behaviour"][key]]
print("Behaviour that differs:")
for key in changed:
    print(f"  {key:<40} {old['behaviour'][key]!s:>24}  ->  {new['behaviour'][key]!s}")
print(f"\nBehaviour that is the same: {len(old['behaviour']) - len(changed)} of {len(old['behaviour'])} probes")
for key in old["behaviour"]:
    if key not in changed:
        print(f"  {key:<40} {old['behaviour'][key]!s:>24}")
print("\nMedian wall time, milliseconds (one shared machine; indicative only):")
for key, before in old["timingsMs"].items():
    after = new["timingsMs"][key]
    print(f"  {key:<40} {before:>10.2f}  ->  {after:>8.2f}   {(after - before) / before * 100:+6.1f}%")
