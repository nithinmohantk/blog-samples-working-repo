"""Parse Kubernetes resource quantities into exact byte counts.

Only what memory comparisons need: binary (Ki..Ei) and decimal (k..E, m)
suffixes and plain or exponent numbers. Decimal arithmetic keeps "0.5Gi" and
"512Mi" equal instead of nearly equal.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

_BINARY = {"Ki": 2**10, "Mi": 2**20, "Gi": 2**30, "Ti": 2**40, "Pi": 2**50, "Ei": 2**60}
_DECIMAL = {
    "m": Decimal("0.001"),
    "": Decimal(1),
    "k": Decimal(10) ** 3,
    "M": Decimal(10) ** 6,
    "G": Decimal(10) ** 9,
    "T": Decimal(10) ** 12,
    "P": Decimal(10) ** 15,
    "E": Decimal(10) ** 18,
}
_PATTERN = re.compile(r"^([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)(Ki|Mi|Gi|Ti|Pi|Ei|m|k|M|G|T|P|E)?$")


class QuantityError(ValueError):
    """Raised when a value is not a valid Kubernetes quantity."""


def parse_quantity(value: object) -> Decimal:
    """Return the quantity as an exact Decimal in base units (bytes for memory)."""
    if isinstance(value, bool) or value is None:
        raise QuantityError(f"not a quantity: {value!r}")
    text = str(value).strip()
    match = _PATTERN.match(text)
    if not match:
        raise QuantityError(f"not a quantity: {value!r}")
    number, suffix = match.group(1), match.group(2) or ""
    try:
        amount = Decimal(number)
    except InvalidOperation as exc:  # pragma: no cover - the regex already filters these
        raise QuantityError(f"not a quantity: {value!r}") from exc
    if suffix in _BINARY:
        return amount * _BINARY[suffix]
    return amount * _DECIMAL[suffix]
