"""The access path in front of the record: filter for restrictions, then log what was actually shown."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

from .audit import Requester, access_event
from .fhir import FhirClient
from .restrict import Restriction, searchset, visible


class AccessGateway:
    def __init__(self, fhir: FhirClient, restrictions: dict[str, Restriction] | None = None,
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        self.fhir, self.clock = fhir, clock
        self.restrictions = restrictions or {}   # production: a durable store, e.g. FHIR Consent resources

    def search(self, requester: Requester, patient: str, rtype: str, params: dict | None = None,
               *, emergency: bool = False) -> dict:
        query = {"patient": patient, "_count": 100, **(params or {})}
        found, _server_total = self.fhir.search_all(rtype, query)
        shown = visible(found, self.restrictions.get(patient), requester.organization, emergency=emergency)
        # Log before returning: an access that cannot be logged is not served.
        self.fhir.create(access_event(requester, patient, shown, interaction="search-type",
                                      emergency=emergency, when=self.clock()))
        return searchset(shown)
