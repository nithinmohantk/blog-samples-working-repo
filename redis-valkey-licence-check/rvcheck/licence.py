"""Which licence covers a running server, from what the server says about itself.

As announced on 20 March 2024: Redis 7.4 and later are dual-licensed RSALv2 / SSPLv1; Redis 7.2.x and
earlier stay BSD-3-Clause, and security fixes are backported to them under BSD. Valkey (28 March 2024)
continues from Redis 7.2.4 under BSD-3-Clause. Redict (22 March 2024) is LGPL-3.0-only for its changes.
"""
from __future__ import annotations

from dataclasses import dataclass

UNSTABLE = (255, 255, 255)   # what a build of the development branch reports as redis_version


@dataclass(frozen=True)
class Licence:
    product: str
    version: str
    licence: str
    note: str = ""


def _version(text: str) -> tuple[int, ...]:
    try:
        return tuple(int(p) for p in text.split(".")[:3])
    except ValueError:
        return ()


def classify(info: dict) -> Licence:
    """`info` is the parsed INFO SERVER section (redis-py's client.info('server'))."""
    if str(info.get("server_name", "")).lower() == "valkey" or "valkey_version" in info:
        return Licence("Valkey", str(info.get("valkey_version", info.get("redis_version"))), "BSD-3-Clause")
    if "redict_version" in info:
        return Licence("Redict", str(info["redict_version"]), "LGPL-3.0-only (changes); BSD-3-Clause (inherited code)")
    raw = str(info.get("redis_version", ""))
    v = _version(raw)
    if v == UNSTABLE:
        return Licence("Redis-compatible development build", raw, "unknown",
                       "development branches report 255.255.255; check the source the binary was built from "
                       "(Redis unstable after 20 March 2024 is RSALv2/SSPLv1, Valkey is BSD-3-Clause)")
    if not v:
        return Licence("unknown", raw, "unknown")
    if v >= (7, 4):
        return Licence("Redis", raw, "RSALv2 or SSPLv1")
    return Licence("Redis", raw, "BSD-3-Clause")


def classify_image_tag(image: str) -> Licence:
    """For inventories that only have image references, e.g. from a registry or a Helm values file."""
    name, _, tag = image.rpartition(":") if ":" in image.split("/")[-1] else (image, "", "latest")
    base = name.split("/")[-1]
    if base == "valkey":
        return Licence("Valkey", tag, "BSD-3-Clause")
    if base == "redict":
        return Licence("Redict", tag, "LGPL-3.0-only (changes); BSD-3-Clause (inherited code)")
    if base == "redis":
        v = _version(tag.split("-")[0])
        if not v or tag in ("latest", "alpine", "bookworm"):
            return Licence("Redis", tag, "unknown", "floating tag: pin a version, it will move to 7.4")
        return classify({"redis_version": ".".join(map(str, v))})
    return Licence("not Redis", tag, "n/a")
