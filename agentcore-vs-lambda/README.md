# agentcore-vs-lambda

Sample code for the dataa.dev article "Bedrock AgentCore Runtime vs. Lambda for Hosting Agents".

- `agent_core.py` - the agent: a bounded tool loop over the Bedrock Converse API. No hosting code.
- `lambda_handler.py` - host 1, AWS Lambda with conversation state in DynamoDB.
- `agentcore_app.py` - host 2, AgentCore Runtime with conversation state in session memory.
- `invoke_client.py` - calling the AgentCore runtime and ending the session.
- `test_agent.py` - runs all of the above against stubbed AWS clients.

## Run the tests

```
pip install -r requirements.txt
python test_agent.py
```

Expected last line: `ALL TESTS OK`. The tests use botocore stubs, so no AWS account is needed.
Nothing here has been deployed to a live account.
