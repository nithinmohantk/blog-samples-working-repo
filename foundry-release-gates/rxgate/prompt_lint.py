"""Static checks on an agent version's instructions, run before any simulation.

Added after the optimizer's best candidate copied leaflet facts (doses,
monitoring intervals) into the system prompt. A prompt that carries a dose
goes stale silently when the leaflet changes; the corpus is the controlled
source, so clinical figures in instructions block the release.
"""

from __future__ import annotations

import re
from pathlib import Path

CORPUS = Path(__file__).resolve().parent / "corpus"
DOSE = re.compile(r"(?i)\b\d+(?:\.\d+)?\s*(?:mg|ml|micrograms?|mcg)\b(?:\s*/\s*kg)?")
INTERVAL = re.compile(r"(?i)\bevery\s+\d+\s*(?:hours?|days?|weeks?|months?)\b|\b\d+\s*(?:-|to|–)\s*\d+\s*weeks?\b")
MAX_GROWTH = 5.0


def product_names() -> list[str]:
    names = []
    for path in CORPUS.glob("*.md"):
        first = path.read_text(encoding="utf-8").splitlines()[0]
        names.append(first.lstrip("# ").split()[0])
    return sorted(names)


def lint(instructions: str, baseline: str | None = None) -> tuple[list[str], list[str]]:
    """Return (blocking findings, warnings)."""
    blocks: list[str] = []
    warnings: list[str] = []
    doses = sorted(set(m.group(0) for m in DOSE.finditer(instructions)))
    if doses:
        blocks.append(f"instructions hard-code dose figures: {doses}")
    intervals = sorted(set(m.group(0) for m in INTERVAL.finditer(instructions)))
    if intervals:
        blocks.append(f"instructions hard-code clinical intervals: {intervals}")
    named = [n for n in product_names() if re.search(rf"\b{re.escape(n)}\b", instructions, re.IGNORECASE)]
    if named:
        warnings.append(f"instructions name specific products: {named}")
    if baseline and len(instructions) > MAX_GROWTH * len(baseline):
        warnings.append(f"instructions grew {len(instructions) / len(baseline):.1f}x ({len(baseline)} -> {len(instructions)} chars)")
    return blocks, warnings
