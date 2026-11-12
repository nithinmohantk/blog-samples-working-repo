import json, os, sys
os.environ.update(BEDROCK_MODEL_ID="m", SESSIONS_TABLE="t", AWS_DEFAULT_REGION="us-east-1", AWS_ACCESS_KEY_ID="x", AWS_SECRET_ACCESS_KEY="x")
import agent_core
from botocore.stub import Stubber, ANY

def tool_resp(): return {"output":{"message":{"role":"assistant","content":[{"toolUse":{"toolUseId":"tu1","name":"get_order_status","input":{"order_id":"ORD-10042"}}}]}},"stopReason":"tool_use","usage":{"inputTokens":10,"outputTokens":5,"totalTokens":15},"metrics":{"latencyMs":1}}
def final_resp(t="It has shipped."): return {"output":{"message":{"role":"assistant","content":[{"text":t}]}},"stopReason":"end_turn","usage":{"inputTokens":20,"outputTokens":5,"totalTokens":25},"metrics":{"latencyMs":1}}
EXP={"modelId":"m","system":ANY,"messages":ANY,"toolConfig":ANY,"inferenceConfig":ANY}

# 1. core loop
with Stubber(agent_core.bedrock) as s:
    s.add_response("converse", tool_resp(), EXP); s.add_response("converse", final_resp(), EXP)
    h=[]; assert agent_core.run_turn(h,"Where is ORD-10042?")=="It has shipped."; s.assert_no_pending_responses()
    assert [m["role"] for m in h]==["user","assistant","user","assistant"]
    assert h[2]["content"][0]["toolResult"]["content"][0]["json"]=={"order_id":"ORD-10042","status":"SHIPPED"}
for bad in ["", None, "x"*5000]:
    try: agent_core.run_turn([],bad); assert False
    except agent_core.InvalidRequest: pass
with Stubber(agent_core.bedrock) as s:
    for _ in range(6): s.add_response("converse", tool_resp(), EXP)
    try: agent_core.run_turn([],"loop"); assert False
    except RuntimeError as e: assert "6 model calls" in str(e)
r=agent_core._run_tool({"toolUseId":"a","name":"nope","input":{}}); assert r["toolResult"]["status"]=="error"
r=agent_core._run_tool({"toolUseId":"a","name":"get_order_status","input":{"order_id":"bad"}}); assert r["toolResult"]["status"]=="error"

# 2. AgentCore host via the real SDK app
from starlette.testclient import TestClient
import agentcore_app
c=TestClient(agentcore_app.app)
assert c.get("/ping").json()["status"]=="Healthy"
H={"X-Amzn-Bedrock-AgentCore-Runtime-Session-Id":"s"*36}
with Stubber(agent_core.bedrock) as s:
    s.add_response("converse", final_resp("one"), EXP); s.add_response("converse", final_resp("two"), EXP)
    r1=c.post("/invocations",json={"prompt":"hi"},headers=H); r2=c.post("/invocations",json={"prompt":"again"},headers=H)
    assert r1.status_code==200 and r1.json()=={"answer":"one","sessionId":"s"*36,"messagesInSession":2}, r1.text
    assert r2.json()["messagesInSession"]==4, r2.text
r=c.post("/invocations",json={"prompt":""},headers=H); assert r.status_code==400 and "prompt" in r.json()["error"], r.text

# 3. Lambda host with a fake table
import lambda_handler as L
class FakeTable:
    def __init__(s): s.items={}; s.fail=False
    class meta:
        class client:
            class exceptions:
                class ConditionalCheckFailedException(Exception): pass
    def get_item(s,Key,ConsistentRead): 
        i=s.items.get(Key["sessionId"]); return {"Item":i} if i else {}
    def put_item(s,Item,ConditionExpression):
        if s.fail: raise s.meta.client.exceptions.ConditionalCheckFailedException()
        s.items[Item["sessionId"]]=Item
L.table=FakeTable(); sid="a"*36
with Stubber(agent_core.bedrock) as s:
    s.add_response("converse", final_resp("one"), EXP); s.add_response("converse", final_resp("two"), EXP)
    r=L.handler({"body":json.dumps({"sessionId":sid,"prompt":"hi"})},None); assert r["statusCode"]==200 and json.loads(r["body"])["answer"]=="one"
    r=L.handler({"body":json.dumps({"sessionId":sid,"prompt":"again"})},None); assert r["statusCode"]==200
    it=L.table.items[sid]; assert it["version"]==2 and len(json.loads(it["history"]))==4 and it["expiresAt"]>0
assert L.handler({"body":json.dumps({"sessionId":"short","prompt":"hi"})},None)["statusCode"]==400
assert L.handler({"body":"{nope"},None)["statusCode"]==400
assert L.handler({"body":json.dumps({"sessionId":sid,"prompt":""})},None)["statusCode"]==400
L.table.fail=True
with Stubber(agent_core.bedrock) as s:
    s.add_response("converse", final_resp("x"), EXP)
    assert L.handler({"body":json.dumps({"sessionId":sid,"prompt":"hi"})},None)["statusCode"]==409
print("ALL TESTS OK")
