import json, os
os.environ.update(BEDROCK_MODEL_ID="m", AWS_DEFAULT_REGION="us-east-1", AWS_ACCESS_KEY_ID="x", AWS_SECRET_ACCESS_KEY="x",
                  AZURE_OPENAI_ENDPOINT="https://example.openai.azure.com", AZURE_OPENAI_API_VERSION="2024-10-21", AZURE_OPENAI_DEPLOYMENT="dep")
from botocore.stub import Stubber
import bedrock_cached as B
from cache_stats import CacheStats

def resp(read, write, inp):
    return {"output":{"message":{"role":"assistant","content":[{"text":"ok"}]}},"stopReason":"end_turn","metrics":{"latencyMs":1},
            "usage":{"inputTokens":inp,"outputTokens":7,"totalTokens":inp+7+read+write,"cacheReadInputTokens":read,"cacheWriteInputTokens":write}}
def expect(cp): return {"modelId":"m","system":[{"text":"S"},{"cachePoint":cp}],"messages":[{"role":"user","content":[{"text":"q"}]}],"inferenceConfig":{"maxTokens":800}}
with Stubber(B.bedrock) as s:
    s.add_response("converse", resp(0,2000,12), expect({"type":"default"}))
    s.add_response("converse", resp(2000,0,12), expect({"type":"default"}))
    s.add_response("converse", resp(2000,0,12), expect({"type":"default","ttl":"1h"}))
    t,a=B.ask("S","q"); assert t=="ok" and a==CacheStats(12,0,2000,7) and a.read_ratio==0
    t,b=B.ask("S","q"); assert b.cache_read_tokens==2000 and abs(b.read_ratio-2000/2012)<1e-9
    B.ask("S","q",one_hour=True); s.assert_no_pending_responses()
assert CacheStats(0,0,0,0).read_ratio==0.0

# Azure: real SDK client, fake HTTP transport
import httpx, azure_cached as A
from openai import AzureOpenAI
seen={}
def handler(request):
    seen["url"]=str(request.url); seen["auth"]=request.headers.get("authorization"); seen["body"]=json.loads(request.content)
    return httpx.Response(200,json={"id":"x","object":"chat.completion","created":1,"model":"gpt","choices":[{"index":0,"finish_reason":"stop","message":{"role":"assistant","content":"hello"}}],
        "usage":{"prompt_tokens":1566,"completion_tokens":20,"total_tokens":1586,"prompt_tokens_details":{"cached_tokens":1408,"audio_tokens":0}}})
A.client=AzureOpenAI(azure_endpoint="https://example.openai.azure.com",api_version="2024-10-21",azure_ad_token_provider=lambda:"tok",http_client=httpx.Client(transport=httpx.MockTransport(handler)))
t,st=A.ask("S"*10,"q"); assert t=="hello" and st==CacheStats(158,1408,0,20), st
assert "/openai/deployments/dep/chat/completions" in seen["url"] and seen["auth"]=="Bearer tok" and seen["body"]["messages"][0]["role"]=="system" and seen["body"]["max_completion_tokens"]==800
print("ALL TESTS OK")
