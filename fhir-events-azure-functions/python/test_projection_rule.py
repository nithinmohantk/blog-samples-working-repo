"""Runs the scenario shared with the C# self-test (../tests/scenario.json) through the Python rule.

    python test_projection_rule.py
"""
import json
import pathlib

import projection_rule as rule

scenario = json.loads((pathlib.Path(__file__).parent.parent / "tests" / "scenario.json").read_text(encoding="utf-8"))
server: dict[str, dict] = {}
store = rule.InMemoryStore()
reads = 0


def read_current(resource_id: str):
    global reads
    reads += 1
    state = server.get(resource_id)
    if state is None or state.get("deleted"):
        return None
    observation = {"resourceType": "Observation", "id": resource_id, "status": state["status"], "component": [
        {"code": {"coding": [{"code": "8480-6"}]}, "valueQuantity": {"value": state["systolic"]}},
        {"code": {"coding": [{"code": "8462-4"}]}, "valueQuantity": {"value": state["diastolic"]}}]}
    return observation, state["version"]


outcomes, failures = [], 0
for step in scenario["steps"]:
    if "server" in step:
        server[step["server"]["id"]] = step["server"]
        continue
    outcome = rule.handle(step["event"], store, read_current)
    outcomes.append(outcome)
    if outcome != step["expect"]:
        failures += 1
        print(f"FAIL  {step['event']} -> {outcome}, expected {step['expect']}")

for resource_id, expected in scenario["expectProjection"].items():
    row = store.rows[resource_id]
    actual = {"version": row.version, "deleted": row.deleted, "retracted": row.retracted, "systolic": row.systolic}
    if actual != expected:
        failures += 1
        print(f"FAIL  projection {resource_id}: {actual}, expected {expected}")

pathlib.Path("outcomes.python.json").write_text(json.dumps(outcomes), encoding="utf-8")
print(f"{len(outcomes)} deliveries, {reads} reads of the FHIR server, {failures} failures")
raise SystemExit(1 if failures else 0)
