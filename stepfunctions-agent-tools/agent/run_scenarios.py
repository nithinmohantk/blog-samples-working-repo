"""Runs the goodwill-credit workflow on Step Functions Local, driven the way an agent would drive it.

    python run_scenarios.py http://127.0.0.1:8083 [results.json]

Lambda tasks are answered by the mock configuration; the approval step is a real activity task with a real
task token, completed by a worker in this script that stands for the approver's application. Nothing here
calls AWS.
"""
import json
import pathlib
import sys
import time

import boto3
import botocore.config
import botocore.exceptions

from gateway_emulator import GatewayEmulator

root = pathlib.Path(__file__).resolve().parent.parent
endpoint = sys.argv[1]
sfn = boto3.client(
    "stepfunctions", endpoint_url=endpoint, region_name="us-east-1",
    aws_access_key_id="local", aws_secret_access_key="local",  # throwaway values; Step Functions Local ignores them
    config=botocore.config.Config(read_timeout=75, retries={"max_attempts": 1}),
)
target = json.loads((root / "gateway" / "target.json").read_text(encoding="utf-8"))
definition = (root / "workflow" / "goodwill-credit.asl.json").read_text(encoding="utf-8")
ROLE = "arn:aws:iam::123456789012:role/local-only"

for attempt in range(60):  # the container accepts connections before the service inside it is ready
    try:
        sfn.list_state_machines()
        break
    except botocore.exceptions.BotoCoreError:
        time.sleep(1)

activity_arn = sfn.create_activity(name="ManagerApproval")["activityArn"]
machine_arn = sfn.create_state_machine(name="GoodwillCredit", definition=definition, roleArn=ROLE)["stateMachineArn"]
assert '"TimeoutSeconds": 86400' in definition
short_arn = sfn.create_state_machine(  # the same workflow with a 3-second approval window, to test expiry
    name="GoodwillCreditShortApproval", definition=definition.replace('"TimeoutSeconds": 86400', '"TimeoutSeconds": 3'), roleArn=ROLE,
)["stateMachineArn"]

passed = failed = 0
results: dict[str, dict] = {}


def check(name: str, condition: bool, detail: str = "") -> None:
    global passed, failed
    passed += bool(condition)
    failed += not condition
    print(f"{'ok  ' if condition else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not condition else ""))


def gateway(test_case: str, arn: str = machine_arn) -> GatewayEmulator:
    return GatewayEmulator(sfn, target, state_machine_arn=f"{arn}#{test_case}")


def text(result: dict) -> dict:
    return json.loads(result["content"][0]["text"])


def start(gw: GatewayEmulator, name: str, payload: dict) -> dict:
    return gw.call("credit___StartExecution", {"name": name, "input": json.dumps(payload)})


def wait(gw: GatewayEmulator, execution_arn: str, seconds: float = 30) -> dict:
    deadline = time.monotonic() + seconds
    while True:
        described = text(gw.call("credit___DescribeExecution", {"executionArn": execution_arn, "includedData": "ALL_DATA"}))
        if described["status"] != "RUNNING" or time.monotonic() > deadline:
            return described
        time.sleep(0.25)


def history(execution_arn: str) -> list[dict]:
    events, token = [], None
    while True:
        page = sfn.get_execution_history(executionArn=execution_arn, maxResults=1000, **({"nextToken": token} if token else {}))
        events += page["events"]
        token = page.get("nextToken")
        if not token:
            return events


def path(events: list[dict]) -> list[str]:
    return [e["stateEnteredEventDetails"]["name"] for e in events if "stateEnteredEventDetails" in e]


def approve(approved: bool) -> dict:
    """The approver's side: receive the task token, decide, return it. The agent never holds the token."""
    task = sfn.get_activity_task(activityArn=activity_arn, workerName="approvals-app")
    sfn.send_task_success(taskToken=task["taskToken"], output=json.dumps({"approved": approved, "approver": "manager-7"}))
    return json.loads(task["input"])


def run(label: str, gw: GatewayEmulator, name: str, payload: dict, approval: bool | None = None) -> tuple[dict, list[dict]]:
    started = start(gw, name, payload)
    assert not started["isError"], started
    arn = text(started)["executionArn"]
    waiting = None
    if approval is not None:
        waiting = text(gw.call("credit___DescribeExecution", {"executionArn": arn}))
        approve(approval)
    described = wait(gw, arn)
    events = history(arn)
    output = json.loads(described["output"]) if described.get("output") else None
    results[label] = {"status": described["status"], "output": output, "path": path(events), "events": len(events)}
    if waiting is not None:
        results[label]["status_while_waiting"] = waiting["status"]
    return results[label], events


gw = gateway("HappyPath")
tools = {tool["name"]: tool for tool in gw.list_tools()}
check("the agent is offered four tools and none that returns a task token",
      sorted(tools) == ["credit___DescribeExecution", "credit___GetExecutionHistory", "credit___ListExecutions", "credit___StartExecution"])
check("StartExecution advertises input and name, and not the state machine",
      sorted(tools["credit___StartExecution"]["inputSchema"]["properties"]) == ["input", "name"])

small, events = run("small_credit", gw, "credit-C1001-20261101", {"caseId": "C1001", "amountCents": 2500})
check("a small credit is applied without a person", small["status"] == "SUCCEEDED" and small["output"]["outcome"] == "CREDITED" and "ManagerApproval" not in small["path"], str(small))
scheduled = [json.loads(e["taskScheduledEventDetails"]["parameters"]) for e in events if "taskScheduledEventDetails" in e]
apply_payloads = [p["Payload"] for p in scheduled if p.get("FunctionName") == "credit-apply"]
check("the credit call carries the execution name as its idempotency key",
      len(apply_payloads) == 1 and apply_payloads[0].get("idempotencyKey") == "credit-C1001-20261101", str(scheduled))

again = start(gw, "credit-C1001-20261101", {"caseId": "C1001", "amountCents": 2500})
changed = start(gw, "credit-C1001-20261101", {"caseId": "C1001", "amountCents": 4900})
results["repeat_same_name"] = {"same_input": again["content"][0]["text"][:160], "different_input": changed["content"][0]["text"][:160]}
listed = text(gw.call("credit___ListExecutions", {}))["executions"]
check("starting again under the same name does not run the workflow a second time",
      sum(1 for e in listed if e["name"] == "credit-C1001-20261101") == 1 and changed["isError"], json.dumps(results["repeat_same_name"]))

mid, _ = run("approved_credit", gw, "credit-C1002-20261101", {"caseId": "C1002", "amountCents": 20000}, approval=True)
check("a larger credit waits for a person, and is applied after approval",
      mid["status_while_waiting"] == "RUNNING" and mid["output"]["outcome"] == "CREDITED" and mid["path"].index("ManagerApproval") < mid["path"].index("ApplyCredit"), str(mid))

declined, _ = run("declined_credit", gw, "credit-C1003-20261101", {"caseId": "C1003", "amountCents": 20000}, approval=False)
check("a declined credit never reaches the state that moves money",
      declined["output"]["outcome"] == "DECLINED" and "ApplyCredit" not in declined["path"], str(declined))

over, _ = run("over_limit", gw, "credit-C1004-20261101", {"caseId": "C1004", "amountCents": 90000})
check("an amount above the limit is refused with no approval asked and no credit",
      over["output"]["outcome"] == "REJECTED" and not {"ManagerApproval", "ApplyCredit"} & set(over["path"]), str(over))

for label, payload in (("amount_as_text", {"caseId": "C1005", "amountCents": "2500"}), ("negative_amount", {"caseId": "C1006", "amountCents": -100}),
                       ("missing_case", {"amountCents": 2500})):
    bad, _ = run(label, gw, f"credit-bad-{label.replace('_', '-')}", payload)
    check(f"malformed input ({label.replace('_', ' ')}) is refused before any task runs",
          bad["output"]["outcome"] == "REJECTED" and bad["path"] == ["CheckInputShape", "RejectInvalidInput"], str(bad))

ineligible, _ = run("ineligible", gateway("Ineligible"), "credit-C1007-20261101", {"caseId": "C1007", "amountCents": 2500})
check("a case the system of record calls ineligible is refused with its reason",
      ineligible["output"] == {"outcome": "REJECTED", "reason": "The case is closed."} and "ApplyCredit" not in ineligible["path"], str(ineligible))

recovers, events = run("apply_recovers", gateway("ApplyRecovers"), "credit-C1008-20261101", {"caseId": "C1008", "amountCents": 2500})
attempts = sum(1 for e in events if e["type"] == "TaskScheduled" and json.loads(e["taskScheduledEventDetails"]["parameters"]).get("FunctionName") == "credit-apply")
results["apply_recovers"]["apply_attempts"] = attempts
check("two transient failures of the credit call are retried by the workflow, not by the agent",
      recovers["output"]["outcome"] == "CREDITED" and attempts == 3, f"attempts={attempts} {recovers}")

down, _ = run("apply_down", gateway("ApplyDown"), "credit-C1009-20261101", {"caseId": "C1009", "amountCents": 2500})
check("when the credit call stays down the execution fails, and the agent is told FAILED", down["status"] == "FAILED" and down["output"] is None, str(down))

short = gateway("HappyPath", short_arn)
started = text(start(short, "credit-C1010-20261101", {"caseId": "C1010", "amountCents": 20000}))
expired = wait(short, started["executionArn"])
results["approval_expired"] = {"status": expired["status"], "output": json.loads(expired["output"]) if expired.get("output") else None, "path": path(history(started["executionArn"]))}
check("an approval nobody answers expires, and nothing is credited",
      results["approval_expired"]["output"] == {"outcome": "EXPIRED", "reason": "Nobody approved the credit in time."} and "ApplyCredit" not in results["approval_expired"]["path"], str(results["approval_expired"]))

hijack = gw.call("credit___StartExecution", {"input": "{}", "stateMachineArn": short_arn})
check("the emulator refuses an agent that names a state machine, as the connector documents",
      hijack["isError"] and "cannot set parameter(s): [/stateMachineArn]" in hijack["content"][0]["text"])
check("there is no tool the agent could use to approve its own request", gw.call("credit___SendTaskSuccess", {"taskToken": "x", "output": "{}"})["isError"])

if len(sys.argv) > 2:
    pathlib.Path(sys.argv[2]).write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
print(f"\n{passed} of {passed + failed} checks passed")
sys.exit(1 if failed else 0)
