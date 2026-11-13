"""Four ways to run a booking service in two regions, on the same deterministic workload.

    python simulate.py [results.json]

One booking attempt arrives per tick, at a random region, for a random appointment slot. A write accepted
in one region reaches the other LAG ticks later. One region is unavailable for a window. Each strategy is
scored on what it refuses and on what it tells a patient and later takes back.

  multi-write, last writer wins          both regions accept; a conflict keeps the later write, silently
  multi-write, first writer wins         both regions accept; a conflict keeps the earlier write and
                                         records a compensation for the patient who lost
  single writer per slot                 each slot has a home region; no conflicts, no writes while home is down
  active-passive                         one primary; the standby is promoted after a delay and has not
                                         seen the primary's last unreplicated writes
"""
from __future__ import annotations

import json
import sys

SLOTS, ATTEMPTS, LAG = 2000, 2000, 20
OUTAGE_START, OUTAGE_END, FAILOVER_DELAY = 800, 920, 30
STRATEGIES = ["multi_write_last_writer_wins", "multi_write_first_writer_wins", "single_writer_per_slot", "active_passive"]


class Lcg:
    """A fixed generator, so the C# and Python runs see the same workload."""

    def __init__(self, seed: int) -> None:
        self.state = seed

    def next(self, bound: int) -> int:
        self.state = (self.state * 1664525 + 1013904223) & 0xFFFFFFFF
        return (self.state >> 8) % bound


def simulate(strategy: str, failed_region: int, seed: int = 20261025) -> dict:
    rng = Lcg(seed)
    view = [{}, {}]            # per region: slot -> (patient, tick, region)
    outbox: list[list] = []    # [due tick, from region, slot, (patient, tick, region)]
    acked: set[int] = set()
    counts = {"accepted": 0, "refused_slot_taken": 0, "refused_unavailable": 0, "failed_over": 0,
              "conflicts": 0, "silently_lost": 0, "compensated": 0}
    primary, promoted = 0, False

    def up(region: int, tick: int) -> bool:
        return not (region == failed_region and OUTAGE_START <= tick < OUTAGE_END)

    def book(region: int, slot: int, patient: int, tick: int) -> None:
        if slot in view[region]:
            counts["refused_slot_taken"] += 1
            return
        write = (patient, tick, region)
        view[region][slot] = write
        outbox.append([tick + LAG, region, slot, write])
        acked.add(patient)
        counts["accepted"] += 1

    tick = 0
    while tick < ATTEMPTS or outbox:
        # Replication: a message is delivered once it is due and both ends are up.
        waiting = []
        for message in outbox:
            due, sender, slot, write = message
            receiver = 1 - sender
            if due > tick or not up(sender, tick) or not up(receiver, tick):
                waiting.append(message)
                continue
            local = view[receiver].get(slot)
            if local is None or local == write:
                view[receiver][slot] = write
                continue
            if strategy == "multi_write_last_writer_wins":
                incoming_wins = (write[1], write[2]) > (local[1], local[2])
            else:
                incoming_wins = (write[1], write[2]) < (local[1], local[2])
            if incoming_wins:
                # Each conflict is seen from both sides; count it where the local write loses.
                counts["conflicts"] += 1
                counts["silently_lost" if strategy == "multi_write_last_writer_wins" else "compensated"] += 1
                view[receiver][slot] = write
        outbox[:] = waiting

        if strategy == "active_passive":
            if not promoted and failed_region == primary and tick == OUTAGE_START + FAILOVER_DELAY:
                # Promote the standby. Writes the old primary had not shipped are gone.
                counts["silently_lost"] += len(outbox)
                outbox.clear()
                primary, promoted = 1 - primary, True
            if promoted and tick == OUTAGE_END:
                view[1 - primary] = dict(view[primary])  # the old primary rejoins as a copy

        if tick < ATTEMPTS:
            arrival, slot, patient = rng.next(2), rng.next(SLOTS), tick
            if strategy.startswith("multi_write"):
                target = arrival
                if not up(target, tick):
                    target = 1 - arrival
                    counts["failed_over"] += 1
                book(target, slot, patient, tick)
            elif strategy == "single_writer_per_slot":
                home = slot % 2
                if up(home, tick):
                    book(home, slot, patient, tick)
                else:
                    counts["refused_unavailable"] += 1
            else:
                if up(primary, tick):
                    book(primary, slot, patient, tick)
                else:
                    counts["refused_unavailable"] += 1
        tick += 1

    # Counted a second way: every patient who was told "booked" and does not hold the slot at the end.
    holders = {write[0] for write in view[0].values()}
    counts["acknowledged_then_not_held"] = len(acked - holders)
    counts["final_bookings"] = len(view[0])
    counts["regions_agree"] = view[0] == view[1]
    return counts


def run_all() -> dict:
    return {f"{'north' if failed == 0 else 'west'}_fails": {s: simulate(s, failed) for s in STRATEGIES} for failed in (0, 1)}


if __name__ == "__main__":
    results = run_all()
    for scenario, by_strategy in results.items():
        print(scenario)
        for strategy, counts in by_strategy.items():
            print(f"  {strategy:<32} accepted {counts['accepted']:>3}  taken {counts['refused_slot_taken']:>3}  unavailable {counts['refused_unavailable']:>3}"
                  f"  lost {counts['silently_lost']:>2}  compensated {counts['compensated']:>2}  agree {counts['regions_agree']}")
    if len(sys.argv) > 1:
        with open(sys.argv[1], "w", encoding="utf-8") as handle:
            json.dump(results, handle, indent=2)
