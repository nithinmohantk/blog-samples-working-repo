"""Lint a Step Functions connector target and the gateway role policy before either is deployed.

    python check_target.py target.json service-role-policy.json

The rules come from the connector's documented behaviour: an unpinned pinnable operation is created
successfully and then fails on every call; the six unpinnable operations are bounded only by IAM; and the
task-token operations cannot be scoped in IAM at all.
"""
import json
import sys

PINNABLE = {"StartExecution", "StartSyncExecution", "ListExecutions", "DescribeStateMachine"}
EXECUTION_SCOPED = {"DescribeExecution", "StopExecution", "GetExecutionHistory"}
TASK_TOKEN = {"SendTaskSuccess", "SendTaskFailure", "SendTaskHeartbeat"}
ACTION = {op: f"states:{op}" for op in PINNABLE | EXECUTION_SCOPED | TASK_TOKEN}


def as_list(value) -> list:
    return value if isinstance(value, list) else [value]


def check(target: dict, policy: dict) -> list[str]:
    """Returns the findings. An empty list means the pair is consistent."""
    findings: list[str] = []
    connector = target["targetConfiguration"]["mcp"]["connector"]
    if connector["source"].get("connectorId") != "states":
        return ["not a Step Functions connector target"]
    if "version" not in connector["source"]:
        findings.append("connector version is not pinned: the tool schema can change under the agent")

    allowed: dict[str, set[str]] = {}
    for statement in policy["Statement"]:
        if statement.get("Effect") != "Allow":
            continue
        for action in as_list(statement["Action"]):
            if "*" in action:
                findings.append(f"policy grants a wildcard action: {action}")
            allowed.setdefault(action, set()).update(as_list(statement["Resource"]))

    operations = [entry["name"] for entry in connector.get("configurations", [])]
    if not operations:
        findings.append("no operations configured: target creation fails")
    pins: set[str] = set()
    for entry in connector.get("configurations", []):
        name = entry["name"]
        pin = entry.get("parameterValues", {}).get("stateMachineArn")
        if name in PINNABLE:
            if not pin:
                findings.append(f"{name} has no stateMachineArn pin: the tool will fail on every call")
                continue
            pins.add(pin)
            if pin not in allowed.get(ACTION[name], set()):
                findings.append(f"{name} is pinned to a state machine the role may not call")
        if name in TASK_TOKEN:
            findings.append(f"{name} is exposed: the agent could complete an approval it asked for")
        if any(o.get("path") == "$.stateMachineArn" for o in entry.get("parameterOverrides", [])):
            findings.append(f"{name} tries to expose stateMachineArn")
        if name == "StartExecution" and not entry.get("description"):
            findings.append("StartExecution has no description: the model has nothing to decide with")
    if len(pins) > 1:
        findings.append("operations are pinned to different state machines: use one target per workflow")

    machine_names = {pin.rsplit(":", 1)[-1] for pin in pins}
    for name in operations:
        if name not in EXECUTION_SCOPED:
            continue
        resources = allowed.get(ACTION[name], set())
        if not resources:
            findings.append(f"{name} is exposed and the role does not allow it")
        for resource in resources:
            parts = resource.split(":")
            if resource == "*" or len(parts) < 8 or parts[5] != "execution" or parts[6] not in machine_names:
                findings.append(f"{name} can reach executions outside the pinned workflow: {resource}")

    for operation, action in ACTION.items():
        if action in allowed and operation not in operations:
            findings.append(f"role allows {action}, which the target does not expose")
    for action, resources in allowed.items():
        if "*" in resources:
            findings.append(f"{action} is allowed on every resource")
    return findings


if __name__ == "__main__":
    with open(sys.argv[1], encoding="utf-8") as t, open(sys.argv[2], encoding="utf-8") as p:
        result = check(json.load(t), json.load(p))
    for finding in result:
        print("FINDING ", finding)
    print(f"{len(result)} finding(s)")
    sys.exit(1 if result else 0)
