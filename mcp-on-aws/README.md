# MCP on AWS: AgentCore Gateway Lambda target and AgentCore Runtime server

Sample code for the dataa.dev article *Model Context Protocol (MCP) on AWS: Gateway, Runtime and Lambda Patterns for Enterprise Agents* (22 March 2026).

The same two read-only tools are exposed two ways:

| Folder | What it is | MCP code in it |
| :--- | :--- | :--- |
| `gateway_lambda/` | A plain AWS Lambda function used as an Amazon Bedrock AgentCore Gateway target, plus the tool schema to register with the target | None. The gateway speaks MCP. |
| `runtime_server/` | A stateless Streamable HTTP MCP server built with the official MCP Python SDK (`mcp==1.26.0`), for Amazon Bedrock AgentCore Runtime or any container host | `FastMCP` with `stateless_http=True` |
| `sales_tools.py` | Shared business logic: input validation, DynamoDB queries, page-size clamp, pagination tokens bound to one customer | None |

Tools:

- `get_customer_summary(customer_id)`: order count and total spend for one customer.
- `list_customer_orders(customer_id, limit=10, next_token=None)`: one page of orders, newest first, at most 25 per call.

## Data

The functions read a DynamoDB table named by `ORDERS_TABLE_NAME`, partition key `customer_id` (S), sort key `order_id` (S), attributes `amount` (N) and `status` (S). The tests use a synthetic table in moto. There is no real customer data anywhere in this sample.

## Run the tests

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
python -m pytest -q
```

`tests/test_gateway_lambda.py` calls the Lambda handler with the event and `client_context.custom.bedrockAgentCoreToolName` shape that AgentCore Gateway uses (`<target>___<tool>`).

`tests/test_runtime_server.py` starts the MCP server over Streamable HTTP with uvicorn and calls it with the official MCP Python client: `initialize`, `tools/list`, two `tools/call` requests that succeed and one that fails validation.

## Run the server locally

```bash
export ORDERS_TABLE_NAME=CustomerOrders AWS_REGION=eu-west-1
python runtime_server/server.py      # serves http://0.0.0.0:8000/mcp
```

## Deploy

- **Gateway target:** package `sales_tools.py` and `gateway_lambda/handler.py` into one Lambda function (handler `gateway_lambda/handler.lambda_handler`), give its execution role `dynamodb:Query` on the table only, then add it to an AgentCore Gateway as a Lambda target with `gateway_lambda/tool_schema.json` as the tool schema and the gateway IAM role as the outbound credential.
- **Runtime server:** AgentCore Runtime runs ARM64 containers. Build with `docker buildx build --platform linux/arm64 -f runtime_server/Dockerfile -t sales-mcp .`, push to Amazon ECR and create the runtime with the MCP protocol.

## What was verified

- All six tests pass with Python 3.13, `mcp==1.26.0`, `moto` 5.2.5 and `pytest` 9.2.0. The client and server negotiated MCP protocol version `2025-11-25`.
- The summary total is checked against a sum computed independently from the fixture.
- Paging with `limit=25` returns all 30 orders exactly once. A `next_token` from one customer is rejected for another.
- Not verified here: deployment to AWS, the AgentCore Gateway and Runtime themselves, and IAM policies. Those need an AWS account.
