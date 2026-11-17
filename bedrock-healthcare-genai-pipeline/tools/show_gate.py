"""Prints the release decision for a recorded candidate against production."""
import sys
from pathlib import Path

from pipeline import eval_gate as g

data = Path(__file__).resolve().parents[1] / "data"
golden = g.load_golden(data / "golden/golden.jsonl")
current = {"DOC-IM-01", "DOC-ID-02", "DOC-PIA-03"}
production = g.score(golden, g.load_answers(data / "answers/production.jsonl"), current)
candidate = g.score(golden, g.load_answers(data / f"answers/{sys.argv[1]}.jsonl"), current)
promote, reasons = g.decide(candidate, production)
print(f"promote={promote}")
for reason in reasons:
    print(reason)
for failure in candidate.failures:
    print(" ", failure)
