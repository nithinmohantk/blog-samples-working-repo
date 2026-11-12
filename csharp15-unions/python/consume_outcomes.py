"""A non-.NET consumer of the dispense outcomes, reading the JSON Lines file the C# sample writes.

The JSON has no discriminator: each line is the bare shape of one case. A consumer in another language
has to repeat the structural rule the .NET serializer applies, which is what classify() does.

    python consume_outcomes.py outcomes.jsonl
"""
from __future__ import annotations

import collections
import json
import sys


def classify(document: object) -> str:
    """Name the case from the property names alone. Raises ValueError for a shape no case owns."""
    match document:
        case {"prescriptionId": str(), "pharmacy": str(), "at": str(), **rest} if not rest:
            return "dispensed"
        case {"prescriptionId": str(), "code": str(), "reason": str(), **rest} if not rest:
            return "rejected"
        case {"prescriptionId": str(), "question": str(), **rest} if not rest:
            return "referred"
        case _:
            raise ValueError(f"no case has this shape: {sorted(document) if isinstance(document, dict) else type(document).__name__}")


def main() -> int:
    counts: collections.Counter[str] = collections.Counter()
    with open(sys.argv[1], encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                counts[classify(json.loads(line))] += 1
            except ValueError as error:
                print(f"line {number}: {error}")
                return 1
    print(json.dumps(dict(sorted(counts.items()))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
