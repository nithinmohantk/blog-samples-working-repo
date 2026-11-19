# iot-stream-windows

Companion code for the dataa.dev article *IoT Analytics in Real Time: What to Do at the Edge, in the Stream and in the Lake* (13 July 2024).

`streamproc.py` has four small, dependency-free building blocks that show what stream engines do with device telemetry:

| Class | What it does |
| :--- | :--- |
| `Deadband` | Report-by-exception at the edge: forward a reading only when it changes by more than a threshold, or when a heartbeat interval has passed. |
| `Deduplicator` | Drop redelivered messages by ID, with bounded memory (MQTT QoS 1 and most queues deliver at least once). |
| `TumblingWindows` | Event-time windows per device with a watermark and allowed lateness. Late readings from devices that were offline land in the right window; readings later than allowed are counted, not merged into closed results. |
| `HysteresisAlarm` | Raise after N consecutive breaches, clear only below a lower threshold, so a value at the limit does not flap. |

Production systems get these from a stream engine (Apache Flink, including Amazon Managed Service for Apache Flink, or Azure Stream Analytics) or an edge runtime; the point here is to make the settings easy to reason about and test.

## Tests

```bash
pip install pytest==8.2.0
python -m pytest -q
```

8 tests cover deadband forwarding and heartbeats, deduplication and eviction, late and too-late readings, per-device windows, hysteresis, and input validation. Tested with Python 3.12.
