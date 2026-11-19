"""Small, dependency-free building blocks for IoT telemetry processing.

- Deadband: report-by-exception filter for the edge; only forwards a reading
  when it moves more than a threshold or a heartbeat interval has passed.
- Deduplicator: drops redeliveries (MQTT QoS 1 and most queues are
  at-least-once) by message ID within a bounded memory.
- TumblingWindows: event-time windows with a watermark, so readings that
  arrive late (devices buffer while offline) land in the right window, and
  readings later than the allowed lateness are counted instead of silently
  corrupting a closed window.
- HysteresisAlarm: raises after N consecutive breaches and clears only below
  a lower threshold, so a value hovering at the limit does not flap.

These are the patterns stream engines (Apache Flink, Kinesis, Azure Stream
Analytics) provide; seeing them in plain Python makes their settings easier
to reason about.
"""
from __future__ import annotations

from collections import OrderedDict, defaultdict
from dataclasses import dataclass


@dataclass(frozen=True)
class Reading:
    device: str
    ts: float          # event time, seconds since epoch, set by the device
    value: float
    msg_id: str = ""


class Deadband:
    def __init__(self, threshold: float, heartbeat_s: float):
        if threshold < 0 or heartbeat_s <= 0:
            raise ValueError("threshold must be >= 0 and heartbeat_s > 0")
        self.threshold, self.heartbeat = threshold, heartbeat_s
        self._last: dict[str, Reading] = {}

    def accept(self, r: Reading) -> bool:
        last = self._last.get(r.device)
        if last is None or abs(r.value - last.value) > self.threshold or r.ts - last.ts >= self.heartbeat:
            self._last[r.device] = r
            return True
        return False


class Deduplicator:
    def __init__(self, capacity: int = 100_000):
        self.capacity = capacity
        self._seen: OrderedDict[str, None] = OrderedDict()

    def first_time(self, msg_id: str) -> bool:
        if not msg_id:
            return True                     # cannot dedupe without an ID
        if msg_id in self._seen:
            self._seen.move_to_end(msg_id)
            return False
        self._seen[msg_id] = None
        if len(self._seen) > self.capacity:
            self._seen.popitem(last=False)
        return True


@dataclass
class WindowResult:
    device: str
    start: float
    end: float
    count: int
    mean: float
    maximum: float


class TumblingWindows:
    """Event-time tumbling windows per device with a watermark.

    The watermark is the highest event time seen minus `allowed_lateness_s`.
    A window is emitted once the watermark passes its end; readings for an
    already-emitted window are counted in `too_late`.
    """

    def __init__(self, size_s: float, allowed_lateness_s: float):
        if size_s <= 0 or allowed_lateness_s < 0:
            raise ValueError("size_s must be > 0 and allowed_lateness_s >= 0")
        self.size, self.lateness = size_s, allowed_lateness_s
        self._open: dict[tuple[str, float], list[float]] = defaultdict(list)
        self._max_ts = float("-inf")
        self._emitted_until: dict[str, float] = defaultdict(lambda: float("-inf"))
        self.too_late = 0

    def _start(self, ts: float) -> float:
        return ts - (ts % self.size)

    @property
    def watermark(self) -> float:
        return self._max_ts - self.lateness

    def add(self, r: Reading) -> list[WindowResult]:
        start = self._start(r.ts)
        if start + self.size <= self._emitted_until[r.device]:
            self.too_late += 1
            return []
        self._open[(r.device, start)].append(r.value)
        self._max_ts = max(self._max_ts, r.ts)
        return self._close_ready()

    def _close_ready(self, force: bool = False) -> list[WindowResult]:
        out = []
        for (device, start) in sorted(self._open, key=lambda k: k[1]):
            end = start + self.size
            if force or end <= self.watermark:
                vals = self._open.pop((device, start))
                out.append(WindowResult(device, start, end, len(vals), sum(vals) / len(vals), max(vals)))
                self._emitted_until[device] = max(self._emitted_until[device], end)
        return out

    def flush(self) -> list[WindowResult]:
        return self._close_ready(force=True)


class HysteresisAlarm:
    def __init__(self, raise_above: float, clear_below: float, consecutive: int = 3):
        if clear_below >= raise_above:
            raise ValueError("clear_below must be lower than raise_above")
        self.hi, self.lo, self.n = raise_above, clear_below, consecutive
        self._breaches: dict[str, int] = defaultdict(int)
        self.active: set[str] = set()

    def update(self, device: str, value: float) -> str | None:
        """Return 'RAISED', 'CLEARED' or None."""
        if device in self.active:
            if value < self.lo:
                self.active.discard(device)
                self._breaches[device] = 0
                return "CLEARED"
            return None
        self._breaches[device] = self._breaches[device] + 1 if value > self.hi else 0
        if self._breaches[device] >= self.n:
            self.active.add(device)
            return "RAISED"
        return None
