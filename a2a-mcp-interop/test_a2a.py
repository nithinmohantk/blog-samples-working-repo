"""Local tests, no AWS account needed.
Start the tool server first:  python orders_mcp_server.py
Then run:                     python test_a2a.py
"""
import asyncio

import httpx

from order_agent_a2a import build_app

V03 = {"jsonrpc": "2.0", "id": "1", "method": "message/send", "params": {"message": {
    "kind": "message", "role": "user", "messageId": "m1",
    "parts": [{"kind": "text", "text": "Where is ORD-10042?"}]}}}
V10 = {"jsonrpc": "2.0", "id": "2", "method": "SendMessage", "params": {"message": {
    "role": "ROLE_USER", "messageId": "m2", "parts": [{"text": "Where is ORD-10042?"}]}}}


async def main() -> None:
    transport = httpx.ASGITransport(app=build_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost:9000") as http:
        assert (await http.get("/ping")).json() == {"status": "Healthy"}

        card = (await http.get("/.well-known/agent-card.json")).json()
        versions = [i["protocolVersion"] for i in card["supportedInterfaces"]]
        assert versions == ["1.0", "0.3"], versions
        assert card["url"] and card["protocolVersion"] == "0.3"     # legacy fields for 0.3 clients

        old = (await http.post("/", json=V03)).json()
        print("0.3 ->", old)
        assert old["result"]["kind"] == "task" and old["result"]["status"]["state"] == "completed"
        assert "SHIPPED" in old["result"]["artifacts"][0]["parts"][0]["text"]

        new = (await http.post("/", json=V10, headers={"A2A-Version": "1.0"})).json()
        print("1.0 ->", new)
        task = new["result"]["task"]
        assert task["status"]["state"] == "TASK_STATE_COMPLETED"
        assert "SHIPPED" in task["artifacts"][0]["parts"][0]["text"]

        # A 1.0 method without the version header is treated as 0.3 and rejected.
        skew = (await http.post("/", json=V10)).json()
        print("skew ->", skew["error"]["code"], skew["error"]["message"])
        assert skew["error"]["code"] == -32009
    print("ALL A2A TESTS OK")


asyncio.run(main())
