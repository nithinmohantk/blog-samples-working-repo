"""python test_check_target.py"""
import copy
import json
import pathlib
import sys

from check_target import check

here = pathlib.Path(__file__).parent
target = json.loads((here / "target.json").read_text(encoding="utf-8"))
policy = json.loads((here / "service-role-policy.json").read_text(encoding="utf-8"))
passed = failed = 0


def expect(name: str, findings: list[str], fragment: str | None) -> None:
    global passed, failed
    ok = (not findings) if fragment is None else any(fragment in f for f in findings)
    passed += ok
    failed += not ok
    print(f"{'ok  ' if ok else 'FAIL'}  {name}" + ("" if ok else f"  -> {findings}"))


def configs(t: dict) -> list:
    return t["targetConfiguration"]["mcp"]["connector"]["configurations"]


expect("the sample target and policy are consistent", check(target, policy), None)

t = copy.deepcopy(target); del configs(t)[0]["parameterValues"]
expect("an unpinned StartExecution is found", check(t, policy), "no stateMachineArn pin")

t = copy.deepcopy(target); configs(t).append({"name": "SendTaskSuccess"})
expect("an exposed SendTaskSuccess is found", check(t, policy), "could complete an approval")

t = copy.deepcopy(target); configs(t).append({"name": "StopExecution"})
expect("an operation the role does not allow is found", check(t, policy), "role does not allow it")

t = copy.deepcopy(target); configs(t)[1]["parameterValues"]["stateMachineArn"] += "Other"
expect("two workflows on one target are found", check(t, policy), "one target per workflow")

t = copy.deepcopy(target); del t["targetConfiguration"]["mcp"]["connector"]["source"]["version"]
expect("an unpinned connector version is found", check(t, policy), "version is not pinned")

t = copy.deepcopy(target); del configs(t)[0]["description"]
expect("a StartExecution with no description is found", check(t, policy), "nothing to decide with")

p = copy.deepcopy(policy); p["Statement"][1]["Resource"] = "arn:aws:states:eu-west-1:123456789012:execution:*"
expect("execution access wider than the workflow is found", check(target, p), "outside the pinned workflow")

p = copy.deepcopy(policy); p["Statement"][0]["Action"] = "states:*"
expect("a wildcard action is found", check(target, p), "wildcard action")

p = copy.deepcopy(policy); p["Statement"].append({"Effect": "Allow", "Action": "states:SendTaskSuccess", "Resource": "*"})
expect("a task-token permission the target does not need is found", check(target, p), "does not expose")

print(f"\n{passed} of {passed + failed} checks passed")
sys.exit(1 if failed else 0)
