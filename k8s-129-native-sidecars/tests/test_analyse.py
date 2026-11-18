import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sidecars"))
from analyse import containers, last_terminated, parse_events, parse_stream, relative, seconds_between  # noqa: E402

POD = {
    "status": {
        "initContainerStatuses": [{
            "name": "proxy", "restartCount": 0, "ready": True,
            "state": {"running": {"startedAt": "2024-02-17T09:00:00Z"}},
        }],
        "containerStatuses": [{
            "name": "main", "restartCount": 0, "ready": False,
            "state": {"terminated": {"startedAt": "2024-02-17T09:00:09Z", "finishedAt": "2024-02-17T09:00:14Z",
                                     "exitCode": 0, "reason": "Completed"}},
        }],
    }
}


def test_containers_merges_init_and_main_statuses():
    c = containers(POD)
    assert c["proxy"]["kind"] == "init" and c["proxy"]["finished"] is None
    assert c["main"] == {"kind": "main", "started": "2024-02-17T09:00:09Z", "finished": "2024-02-17T09:00:14Z",
                         "exit_code": 0, "reason": "Completed", "restarts": 0, "ready": False}


def test_seconds_between():
    assert seconds_between("2024-02-17T09:00:00Z", "2024-02-17T09:00:09Z") == 9.0
    assert seconds_between(None, "2024-02-17T09:00:09Z") is None


def test_parse_stream_splits_concatenated_objects():
    text = json.dumps({"a": 1}, indent=4) + "\n" + json.dumps({"a": 2}) + "\n"
    assert parse_stream(text) == [{"a": 1}, {"a": 2}]


def test_parse_stream_drops_a_truncated_tail():
    text = json.dumps({"a": 1}) + "\n" + json.dumps({"a": 2, "b": [1, 2]})[:-6]
    assert parse_stream(text) == [{"a": 1}]


def test_last_terminated_keeps_the_latest_state():
    running = json.loads(json.dumps(POD))
    running["status"]["containerStatuses"][0]["state"] = {"running": {"startedAt": "2024-02-17T09:00:09Z"}}
    assert last_terminated([running, POD])["main"]["exit_code"] == 0
    assert "main" not in last_terminated([running])


def test_events_are_sorted_and_made_relative():
    log = "105.20 second-sidecar TERM\n100.10 main TERM\n103.15 main exit\n99.00 main start\n"
    events = parse_events(log)
    assert relative(events, ("main", "TERM")) == [(0.0, "main", "TERM"), (3.05, "main", "exit"),
                                                   (5.1, "second-sidecar", "TERM")]


def test_native_sidecars_are_init_containers_with_restart_policy_always():
    for path in (ROOT / "manifests").glob("*.yaml"):
        doc = yaml.safe_load(path.read_text())
        spec = doc["spec"]["template"]["spec"] if doc["kind"] == "Job" else doc["spec"]
        for init in spec.get("initContainers", []):
            assert init.get("restartPolicy") == "Always", path.name
