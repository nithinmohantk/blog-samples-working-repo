"""Detection of Irish personal identifiers in free text.

Used in two places: the training-data gate (anything found blocks the dataset)
and the evaluation gate (anything found in a model answer is a leak).

Formats, from the sources named in the README:
  * IHI: 18-digit GS1 Global Service Relation Number, or the 10-digit
    "human friendly" form (HSE National Policy for IHI Data Standards).
  * PPSN: seven digits, a check letter, optionally a second letter.

Detection is deliberately broad. In a training-data gate a false alarm costs a
reviewer a minute; a miss puts an identifier into model weights, where it
cannot be removed short of retraining.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

_IHI_18 = re.compile(r"(?<!\d)\d{18}(?!\d)")
_IHI_10 = re.compile(r"(?<!\d)\d{10}(?!\d)")
_SPACED_18 = re.compile(r"(?<!\d)(?:\d[ -]?){17}\d(?!\d)")
_PPSN = re.compile(r"(?<![A-Za-z0-9])(\d{7})([A-Wa-w])([A-Za-z]?)(?![A-Za-z0-9])")


class Kind(str, Enum):
    IHI_GSRN = "IHI_GSRN"          # 18 digits, GS1 check digit valid
    IHI_GSRN_UNCHECKED = "IHI_18"  # 18 digits, check digit not valid
    IHI_SHORT = "IHI_10"           # 10 digits (also catches phone numbers)
    PPSN = "PPSN"                  # check character valid
    PPSN_UNCHECKED = "PPSN_FORMAT" # PPSN shape, check character not valid


@dataclass(frozen=True)
class Finding:
    kind: Kind
    start: int
    end: int

    def masked(self, text: str) -> str:
        value = text[self.start:self.end]
        return f"{self.kind.value}:{'*' * (len(value) - 2)}{value[-2:]}"


def gs1_check_digit_ok(digits: str) -> bool:
    """GS1 modulo-10: weights 3,1,3,... from the digit left of the check digit."""
    if not digits.isdigit() or len(digits) < 2:
        return False
    body, check = digits[:-1], int(digits[-1])
    total = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body)))
    return (10 - total % 10) % 10 == check


def ppsn_check_ok(number: str) -> bool:
    """Modulus 23 check character, weights 8..2 on the digits.

    Since 2013 a second letter A or H also carries weight 9 (A=1 ... H=8).
    A remainder of 0 maps to W.
    """
    m = re.fullmatch(r"(\d{7})([A-W])([A-Z]?)", number.upper())
    if not m:
        return False
    digits, check, second = m.groups()
    total = sum(int(d) * w for d, w in zip(digits, range(8, 1, -1)))
    if second in ("A", "H"):
        total += (ord(second) - 64) * 9
    expected = "W" if total % 23 == 0 else chr(64 + total % 23)
    return check == expected


def scan(text: str) -> list[Finding]:
    findings: list[Finding] = []
    taken: list[tuple[int, int]] = []

    def free(a: int, b: int) -> bool:
        return all(b <= s or a >= e for s, e in taken)

    for m in _SPACED_18.finditer(text):
        digits = re.sub(r"\D", "", m.group())
        kind = Kind.IHI_GSRN if gs1_check_digit_ok(digits) else Kind.IHI_GSRN_UNCHECKED
        findings.append(Finding(kind, m.start(), m.end()))
        taken.append(m.span())
    for m in _IHI_18.finditer(text):
        if free(*m.span()):
            kind = Kind.IHI_GSRN if gs1_check_digit_ok(m.group()) else Kind.IHI_GSRN_UNCHECKED
            findings.append(Finding(kind, *m.span()))
            taken.append(m.span())
    for m in _IHI_10.finditer(text):
        if free(*m.span()):
            findings.append(Finding(Kind.IHI_SHORT, *m.span()))
            taken.append(m.span())
    for m in _PPSN.finditer(text):
        if free(*m.span()):
            kind = Kind.PPSN if ppsn_check_ok(m.group()) else Kind.PPSN_UNCHECKED
            findings.append(Finding(kind, *m.span()))
            taken.append(m.span())
    return sorted(findings, key=lambda f: f.start)
