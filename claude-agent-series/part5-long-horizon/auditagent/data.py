"""Synthetic prescriptions for the audit, and the answer key.

The data is generated from a fixed seed, so every run audits the same 48 prescriptions.
The audit rules are applied here, in code, to produce the expected findings; the agent
never sees this module's answer, only the rules in its system prompt and the records
through its tools. That makes each live run scorable for precision and recall.

Everything is invented: no real patients, prescribers or pharmacies.
"""
from __future__ import annotations

import random
from datetime import date, timedelta

AUDIT_DATE = date(2026, 11, 9)
OVERDUE_DAYS = 60
STALE_DAYS = 180
RULES = ("NO_REPEATS", "OVERDUE", "STALE", "DUPLICATE_CLASS")

# Therapeutic classes for the duplicate rule. The agent is not given this table:
# recognising that two medicines share a class is part of the task.
CLASSES: dict[str, str] = {
    "Atorvastatin 20 mg tablets": "statin", "Simvastatin 40 mg tablets": "statin",
    "Rosuvastatin 10 mg tablets": "statin",
    "Ramipril 5 mg capsules": "ace_inhibitor", "Lisinopril 10 mg tablets": "ace_inhibitor",
    "Perindopril 4 mg tablets": "ace_inhibitor",
    "Omeprazole 20 mg capsules": "ppi", "Lansoprazole 30 mg capsules": "ppi",
    "Sertraline 50 mg tablets": "ssri", "Citalopram 20 mg tablets": "ssri",
    "Bisoprolol 5 mg tablets": "beta_blocker", "Atenolol 50 mg tablets": "beta_blocker",
    "Metformin 500 mg tablets": "biguanide", "Amlodipine 5 mg tablets": "ccb",
    "Levothyroxine 50 microgram tablets": "thyroid", "Salbutamol 100 microgram inhaler": "saba",
}
MEDICINES = list(CLASSES)


def _iso(d: date) -> str:
    return d.isoformat()


def generate(seed: int = 7, patients: int = 16, per_patient: int = 3) -> tuple[dict[str, dict], dict[str, list[dict]]]:
    """Return (prescriptions by id, dispense events by id)."""
    rng = random.Random(seed)
    rx: dict[str, dict] = {}
    dispenses: dict[str, list[dict]] = {}
    n = 2000
    for p in range(1, patients + 1):
        meds = rng.sample(MEDICINES, per_patient)
        if p in (3, 9, 14):  # plant same-class pairs
            pair = {3: ("Atorvastatin 20 mg tablets", "Simvastatin 40 mg tablets"),
                    9: ("Omeprazole 20 mg capsules", "Lansoprazole 30 mg capsules"),
                    14: ("Sertraline 50 mg tablets", "Citalopram 20 mg tablets")}[p]
            meds = [pair[0], pair[1], next(m for m in meds if m not in pair and CLASSES[m] not in
                                           (CLASSES[pair[0]],))]
        for med in meds:
            n += 1
            rid = f"RX-{n}"
            issued = AUDIT_DATE - timedelta(days=rng.randint(20, 260))
            status = "cancelled" if rng.random() < 0.12 else "active"
            repeats = rng.choice([0, 1, 2, 3, 5]) if rng.random() < 0.85 else 0
            rx[rid] = {"id": rid, "patient": f"P-{p:03d}", "medication": med, "status": status,
                       "issued": _iso(issued), "repeats_remaining": repeats, "prescriber": "Dr A. Example"}
            events = []
            d = issued + timedelta(days=rng.randint(0, 5))
            while d < AUDIT_DATE and rng.random() < 0.8:
                events.append({"date": _iso(d), "pharmacy": "Example Pharmacy, Galway", "quantity": 28})
                d += timedelta(days=rng.choice([28, 28, 30, 56, 90]))
            dispenses[rid] = events
    # Make the duplicate-class pairs active so the rule applies.
    for p in (3, 9, 14):
        for r in rx.values():
            if r["patient"] == f"P-{p:03d}":
                r["status"] = "active"
    return rx, dispenses


def expected_findings(rx: dict[str, dict], dispenses: dict[str, list[dict]]) -> set[tuple[str, str]]:
    """The answer key: (rx_id, rule) pairs the audit should record."""
    out: set[tuple[str, str]] = set()
    active = [r for r in rx.values() if r["status"] == "active"]
    for r in active:
        issued = date.fromisoformat(r["issued"])
        if r["repeats_remaining"] == 0:
            out.add((r["id"], "NO_REPEATS"))
        else:
            events = dispenses.get(r["id"], [])
            last = date.fromisoformat(events[-1]["date"]) if events else issued
            if (AUDIT_DATE - last).days > OVERDUE_DAYS:
                out.add((r["id"], "OVERDUE"))
        if (AUDIT_DATE - issued).days > STALE_DAYS:
            out.add((r["id"], "STALE"))
    by_patient: dict[tuple[str, str], list[str]] = {}
    for r in active:
        by_patient.setdefault((r["patient"], CLASSES[r["medication"]]), []).append(r["id"])
    for ids in by_patient.values():
        if len(ids) > 1:
            out.update((i, "DUPLICATE_CLASS") for i in ids)
    return out
