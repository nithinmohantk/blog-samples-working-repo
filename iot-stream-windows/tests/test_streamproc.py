import pytest

from streamproc import Deadband, Deduplicator, HysteresisAlarm, Reading, TumblingWindows


def r(ts, v, dev="pump-1", mid=""):
    return Reading(dev, ts, v, mid)


def test_deadband_forwards_changes_and_heartbeats_only():
    db = Deadband(threshold=0.5, heartbeat_s=60)
    sent = [db.accept(x) for x in [r(0, 20.0), r(10, 20.2), r(20, 20.8), r(30, 20.9), r(85, 20.9)]]
    assert sent == [True, False, True, False, True]     # first, >0.5 move, heartbeat at 60 s after last sent


def test_deadband_is_per_device():
    db = Deadband(0.5, 60)
    assert db.accept(r(0, 1.0, "a")) and db.accept(r(0, 1.0, "b"))


def test_deduplicator_drops_redeliveries_and_bounds_memory():
    d = Deduplicator(capacity=2)
    assert [d.first_time(m) for m in ["m1", "m2", "m1", "m3", "m2"]] == [True, True, False, True, True]
    assert d.first_time("") is True


def test_windows_place_late_readings_by_event_time():
    w = TumblingWindows(size_s=60, allowed_lateness_s=30)
    out = []
    out += w.add(r(5, 10))
    out += w.add(r(50, 20))
    out += w.add(r(70, 30))           # watermark 40: window [0,60) still open
    out += w.add(r(40, 40))           # late but within lateness -> joins [0,60)
    assert out == []
    out += w.add(r(95, 50))           # watermark 65: closes [0,60)
    assert len(out) == 1
    first = out[0]
    assert (first.start, first.end, first.count, first.mean, first.maximum) == (0, 60, 3, pytest.approx(70 / 3), 40)


def test_too_late_readings_are_counted_not_merged():
    w = TumblingWindows(60, 10)
    w.add(r(5, 1))
    closed = w.add(r(75, 2))          # watermark 65 closes [0,60)
    assert len(closed) == 1
    assert w.add(r(30, 99)) == [] and w.too_late == 1
    rest = w.flush()
    assert [(x.start, x.count) for x in rest] == [(60, 1)]


def test_windows_are_per_device():
    w = TumblingWindows(60, 0)
    w.add(r(10, 1, "a"))
    w.add(r(20, 2, "b"))
    out = w.add(r(61, 3, "a"))
    assert sorted((x.device, x.count) for x in out) == [("a", 1), ("b", 1)]


def test_hysteresis_needs_consecutive_breaches_and_clears_low():
    a = HysteresisAlarm(raise_above=80, clear_below=70, consecutive=3)
    events = [a.update("pump-1", v) for v in [85, 82, 79, 85, 86, 88, 78, 75, 69]]
    assert events == [None, None, None, None, None, "RAISED", None, None, "CLEARED"]


def test_invalid_settings_rejected():
    with pytest.raises(ValueError):
        HysteresisAlarm(70, 80)
    with pytest.raises(ValueError):
        TumblingWindows(0, 1)
    with pytest.raises(ValueError):
        Deadband(-1, 10)
