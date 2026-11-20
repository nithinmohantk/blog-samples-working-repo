"""A small, synthetic e-prescription service used as the agent's back end.

Everything here is invented test data: no real patients, prescribers or
pharmacies. The service behaves like a typical internal API: lookups that can
fail with "not found", and one state-changing operation with business rules.
"""
from __future__ import annotations

import copy
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone


class RxError(Exception):
    """Base class for domain errors the agent can recover from."""


class NotFound(RxError):
    pass


class Conflict(RxError):
    pass


@dataclass
class RxService:
    prescriptions: dict[str, dict] = field(default_factory=dict)
    dispenses: dict[str, list[dict]] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @classmethod
    def with_sample_data(cls) -> "RxService":
        rx = {
            "RX-1001": {"id": "RX-1001", "patient": "P-001", "medication": "Amoxicillin 500 mg capsules",
                        "dose": "1 capsule three times a day for 7 days", "status": "active",
                        "prescriber": "Dr A. Example", "issued": "2026-10-01"},
            "RX-1002": {"id": "RX-1002", "patient": "P-001", "medication": "Atorvastatin 20 mg tablets",
                        "dose": "1 tablet at night", "status": "active", "repeats_remaining": 4,
                        "prescriber": "Dr A. Example", "issued": "2026-09-12"},
            "RX-1003": {"id": "RX-1003", "patient": "P-002", "medication": "Ramipril 5 mg capsules",
                        "dose": "1 capsule daily", "status": "active", "repeats_remaining": 2,
                        "prescriber": "Dr B. Example", "issued": "2026-10-05"},
        }
        dispenses = {
            "RX-1002": [{"date": "2026-09-13", "pharmacy": "Example Pharmacy, Galway", "quantity": 28},
                        {"date": "2026-10-10", "pharmacy": "Example Pharmacy, Galway", "quantity": 28}],
            "RX-1001": [{"date": "2026-10-01", "pharmacy": "Sample Chemist, Athlone", "quantity": 21}],
        }
        return cls(prescriptions=rx, dispenses=dispenses)

    def find_for_patient(self, patient_id: str) -> list[dict]:
        found = [copy.deepcopy(p) for p in self.prescriptions.values() if p["patient"] == patient_id]
        if not found:
            raise NotFound(f"No prescriptions for patient {patient_id}. Check the patient identifier (format P-000).")
        return found

    def get(self, rx_id: str) -> dict:
        try:
            return copy.deepcopy(self.prescriptions[rx_id])
        except KeyError:
            raise NotFound(f"Prescription {rx_id} does not exist. Identifiers look like RX-1000; "
                           "use find_prescriptions to list a patient's prescriptions.") from None

    def dispense_events(self, rx_id: str) -> list[dict]:
        self.get(rx_id)  # raises NotFound for unknown prescriptions
        return copy.deepcopy(self.dispenses.get(rx_id, []))

    def cancel(self, rx_id: str, reason: str) -> dict:
        with self._lock:
            rx = self.prescriptions.get(rx_id)
            if rx is None:
                raise NotFound(f"Prescription {rx_id} does not exist.")
            if rx["status"] != "active":
                raise Conflict(f"Prescription {rx_id} is already {rx['status']}; only active prescriptions can be cancelled.")
            rx["status"] = "cancelled"
            rx["cancelled"] = {"reason": reason, "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
            return copy.deepcopy(rx)
