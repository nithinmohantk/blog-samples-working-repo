# Step Functions as agent tools

Sample for the dataa.dev article "[Step Functions as Agent Tools: Putting the Rules Where a Prompt Cannot Move Them](https://www.dataa.dev/2026/11/01/step-functions-as-agent-tools-rules-a-prompt-cannot-move/)".

A goodwill-credit workflow that an AI agent may start through the Amazon Bedrock AgentCore Gateway connector
for AWS Step Functions. The agent decides when to ask and for how much. The workflow decides everything
else: input checks, eligibility, limits, who approves, retries, and that a credit is applied once.

Account ids, names and cases are made up. Nothing here calls AWS.

| Path | What it is |
| --- | --- |
| `workflow/goodwill-credit.asl.json` | The Standard workflow: 13 states, 3 tasks, 4 choices |
| `workflow/mock-config.json` | Mocked Lambda responses for Step Functions Local |
| `gateway/target.json` | The connector target: four operations, pinned to one state machine |
| `gateway/service-role-policy.json` | The gateway role's permissions, scoped to that state machine and its executions |
| `gateway/check_target.py` | Lints the target against the policy, with tests |
| `agent/gateway_emulator.py` | A local stand-in for the connector, for tests. It is not the Gateway |
| `agent/run_scenarios.py` | Drives the workflow the way an agent would, plus an approval worker |
| `ci.sh` | Runs all of it |

## Run

    docker run -d -p 8083:8083 \
      -v "$PWD/workflow/mock-config.json:/home/StepFunctionsLocal/MockConfigFile.json:ro" \
      -e SFN_MOCK_CONFIG=/home/StepFunctionsLocal/MockConfigFile.json amazon/aws-stepfunctions-local
    pip install boto3
    python agent/run_scenarios.py http://127.0.0.1:8083

## What was verified

GitHub Actions, `ubuntu-latest`, Python 3.13, boto3 1.44.2, Step Functions Local 2.0.0 (build 2024-05-18) in
Docker. Outputs of the latest run are on the `ci-results-aws` branch under `stepfunctions-agent-tools/`.

| Check | Result |
| --- | --- |
| Target and role policy lint | 0 findings |
| Lint tests (ten broken variants are each found) | 10 of 10 |
| Workflow scenarios | 18 of 18 |

| Scenario | Outcome | States entered |
| --- | --- | --- |
| Credit of 25.00 | `CREDITED`, no person involved | 6 |
| Same execution name again | `ExecutionAlreadyExists`; one execution, one credit | |
| Credit of 200.00, approved | `RUNNING` while waiting, then `CREDITED` | 8 |
| Credit of 200.00, declined | `DECLINED`; `ApplyCredit` never entered | 7 |
| Credit of 900.00 | `REJECTED`, over the limit | 5 |
| Amount as text, negative amount, missing case | `REJECTED` at the first state | 2 |
| Case the system of record calls ineligible | `REJECTED` with its reason | 4 |
| Credit call fails twice, then works | `CREDITED` after 3 attempts by the workflow | 6 |
| Credit call stays down | Execution `FAILED` | 5 |
| Approval taken and never answered | `EXPIRED` | 6 |
| Approval sent after expiry | `TaskTimedOut`; nothing credited | |

## What this does not show

- No AgentCore Gateway and no model were involved. `gateway_emulator.py` applies the connector's documented
  rules (tool naming, the hidden pin, refusal of a pinned parameter) so the agent side can be exercised. The
  real Gateway's authentication, policy engine and error text are not tested here.
- Step Functions Local is an old build and is not the service. It ran this JSONPath workflow, its retries,
  its activity task token and its timeout. Before a deployment, run the same cases in an account.
- The Lambda functions are mocked. The expiry scenario uses a copy of the workflow with a 3-second approval
  window in place of 24 hours.
