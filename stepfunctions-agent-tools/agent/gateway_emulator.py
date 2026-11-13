"""A local stand-in for the AgentCore Gateway Step Functions connector, for tests.

It reads the same target configuration the real Gateway takes and applies the rules the connector
documents: tools are named <target>___<Operation>, a pinned stateMachineArn is removed from the tool schema,
and a call that tries to set it is refused before Step Functions is reached. It is not the Gateway. It has
no authentication, no policy engine and no network boundary; it exists so that the agent side of the
contract can be exercised against a Step Functions endpoint without an AWS account.
"""
import json

import botocore.exceptions

# Fields the agent may set for each operation, before overrides are applied.
AGENT_FIELDS = {
    "StartExecution": {"input": "string"},
    "ListExecutions": {"statusFilter": "string", "maxResults": "integer"},
    "DescribeExecution": {"executionArn": "string", "includedData": "string"},
    "GetExecutionHistory": {"executionArn": "string", "maxResults": "integer", "reverseOrder": "boolean"},
    "StopExecution": {"executionArn": "string", "error": "string", "cause": "string"},
}
BOTO_METHOD = {
    "StartExecution": "start_execution", "ListExecutions": "list_executions", "DescribeExecution": "describe_execution",
    "GetExecutionHistory": "get_execution_history", "StopExecution": "stop_execution",
}


class GatewayEmulator:
    def __init__(self, sfn_client, target: dict, state_machine_arn: str | None = None):
        """state_machine_arn replaces the pin in the target file, so tests can point at a local state machine."""
        self._sfn = sfn_client
        self._prefix = target["name"] + "___"
        self._tools: dict[str, dict] = {}
        for entry in target["targetConfiguration"]["mcp"]["connector"]["configurations"]:
            operation = entry["name"]
            if operation not in AGENT_FIELDS:
                raise ValueError(f"the emulator does not implement {operation}")
            pinned = dict(entry.get("parameterValues", {}))
            if "stateMachineArn" in pinned and state_machine_arn:
                # Step Functions Local selects a mock test case with a "#TestCase" suffix, valid only when starting.
                pinned["stateMachineArn"] = state_machine_arn if operation == "StartExecution" else state_machine_arn.split("#")[0]
            fields = dict(AGENT_FIELDS[operation])
            for override in entry.get("parameterOverrides", []):
                if override.get("visible"):
                    fields[override["path"].removeprefix("$.")] = "string"
            self._tools[self._prefix + operation] = {
                "operation": operation, "pinned": pinned, "fields": fields, "description": entry.get("description", ""),
            }

    def list_tools(self) -> list[dict]:
        return [
            {
                "name": name,
                "description": tool["description"],
                "inputSchema": {"type": "object", "properties": {field: {"type": kind} for field, kind in tool["fields"].items()}},
            }
            for name, tool in self._tools.items()
        ]

    def call(self, name: str, arguments: dict) -> dict:
        tool = self._tools.get(name)
        if tool is None:
            return self._result(f"Unknown tool: {name}", is_error=True)
        refused = sorted(key for key in arguments if key not in tool["fields"])
        if refused:
            paths = ", ".join("/" + key for key in refused)
            return self._result(f"Invalid request parameters: cannot set parameter(s): [{paths}]", is_error=True)

        request = {**arguments, **tool["pinned"]}
        included = request.pop("includedData", "METADATA_ONLY")
        try:
            response = getattr(self._sfn, BOTO_METHOD[tool["operation"]])(**request)
        except botocore.exceptions.ClientError as error:
            code = error.response["Error"]["Code"]
            return self._result(f"DependencyFailedException: {code}: {error.response['Error']['Message']}", is_error=True)
        response.pop("ResponseMetadata", None)
        if tool["operation"] == "DescribeExecution" and included != "ALL_DATA":
            for key in ("input", "output", "inputDetails", "outputDetails"):
                response.pop(key, None)
        return self._result(json.dumps(response, default=str), is_error=False)

    @staticmethod
    def _result(text: str, is_error: bool) -> dict:
        return {"isError": is_error, "content": [{"type": "text", "text": text}]}
