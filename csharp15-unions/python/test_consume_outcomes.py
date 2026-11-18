"""python test_consume_outcomes.py"""
import sys

from consume_outcomes import classify

cases = [
    ("dispensed", {"prescriptionId": "rx-1", "pharmacy": "Main Street", "at": "2026-11-11T09:30:00+00:00"}, "dispensed"),
    ("rejected", {"prescriptionId": "rx-2", "code": "expired", "reason": "Past validity."}, "rejected"),
    ("referred", {"prescriptionId": "rx-3", "question": "Interaction?"}, "referred"),
    ("a fourth case the consumer has never seen", {"prescriptionId": "rx-4", "pharmacy": "Main Street", "quantitySupplied": 14, "quantityOwed": 14}, None),
    ("an extra property on a known case", {"prescriptionId": "rx-3", "question": "Interaction?", "urgent": True}, None),
    ("only the shared property", {"prescriptionId": "rx-5"}, None),
    ("not an object", "dispensed", None),
]
failed = 0
for name, document, expected in cases:
    try:
        actual = classify(document)
    except ValueError:
        actual = None
    failed += actual != expected
    print(f"{'ok  ' if actual == expected else 'FAIL'}  {name}: {actual or 'refused'}")
print(f"\n{len(cases) - failed} of {len(cases)} checks passed")
sys.exit(1 if failed else 0)
