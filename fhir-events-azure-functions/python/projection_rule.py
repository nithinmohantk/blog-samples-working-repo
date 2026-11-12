"""The same projection rule as the C# handler, for a consumer that pulls events from a queue.

The stored version only moves forward. A delivery whose version is not newer than what is stored is a
duplicate or a late arrival and changes nothing. A create or update projects the server's current state,
not the version the event names. A delete writes a tombstone.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

PROJECTED_TYPE = "Observation"


@dataclass(frozen=True)
class Row:
    resource_id: str
    version: int
    deleted: bool = False
    retracted: bool = False
    systolic: Optional[float] = None
    diastolic: Optional[float] = None


class InMemoryStore:
    """Stands in for a table with a conditional upsert. Not safe across processes; a real consumer uses the database."""

    def __init__(self) -> None:
        self.rows: dict[str, Row] = {}

    def get(self, resource_id: str) -> Optional[Row]:
        return self.rows.get(resource_id)

    def upsert_if_newer(self, row: Row) -> bool:
        current = self.rows.get(row.resource_id)
        if current is not None and current.version >= row.version:
            return False
        self.rows[row.resource_id] = row
        return True


def row_from_observation(observation: dict, version: int) -> Row:
    retracted = observation.get("status") == "entered-in-error"

    def component(code: str) -> Optional[float]:
        for part in observation.get("component", []):
            if any(c.get("code") == code for c in part.get("code", {}).get("coding", [])):
                return part.get("valueQuantity", {}).get("value")
        return None

    return Row(observation["id"], version, retracted=retracted,
               systolic=None if retracted else component("8480-6"),
               diastolic=None if retracted else component("8462-4"))


def handle(event: dict, store: InMemoryStore, read_current: Callable[[str], Optional[tuple[dict, int]]]) -> str:
    """event: {"kind": "Created" | "Updated" | "Deleted", "resourceType", "resourceId", "version"}.

    read_current returns (resource, version) or None when the resource is gone. It may raise: let it, so the
    message goes back to the queue and is retried.
    """
    if event.get("resourceType", PROJECTED_TYPE) != PROJECTED_TYPE:
        return "Ignored"
    stored = store.get(event["resourceId"])
    if stored is not None and stored.version >= event["version"]:
        return "SkippedNotNewer"
    if event["kind"] == "Deleted":
        tombstone = Row(event["resourceId"], event["version"], deleted=True)
        return "Tombstoned" if store.upsert_if_newer(tombstone) else "SkippedNotNewer"
    current = read_current(event["resourceId"])
    if current is None:
        return "SkippedGone"
    resource, version = current
    return "Applied" if store.upsert_if_newer(row_from_observation(resource, version)) else "SkippedNotNewer"
