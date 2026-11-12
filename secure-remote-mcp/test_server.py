"""Local test: a throwaway issuer (RSA key + JWKS endpoint) and the real server over HTTP.
Run: python test_server.py"""
import json
import logging
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx
import jwt
import uvicorn
from cryptography.hazmat.primitives.asymmetric import rsa

logging.disable(logging.CRITICAL)      # keep the output to the test lines
ISSUER, RESOURCE = "http://127.0.0.1:9100", "http://127.0.0.1:8000/mcp"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
ROGUE = rsa.generate_private_key(public_exponent=65537, key_size=2048)
JWK = {**json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(KEY.public_key())), "kid": "k1", "use": "sig", "alg": "RS256"}


class Jwks(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps({"keys": [JWK]}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_): pass


def token(scope="orders.read", aud=RESOURCE, exp=300, key=KEY, iss=ISSUER) -> str:
    now = int(time.time())
    claims = {"iss": iss, "aud": aud, "sub": "user-123", "client_id": "test-client", "scope": scope,
              "iat": now, "exp": now + exp}
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "k1"})


os.environ.update(MCP_ISSUER=ISSUER, MCP_JWKS_URI=f"{ISSUER}/jwks", MCP_RESOURCE_URL=RESOURCE,
                  MCP_ALLOWED_HOSTS="127.0.0.1:8000")
threading.Thread(target=HTTPServer(("127.0.0.1", 9100), Jwks).serve_forever, daemon=True).start()
import server  # noqa: E402  (reads the environment at import)

threading.Thread(target=uvicorn.Server(uvicorn.Config(server.app, host="127.0.0.1", port=8000,
                                                      log_level="error")).run, daemon=True).start()
time.sleep(1.5)

INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
    "protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}}
HDR = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


def call(tool: str, tok: str) -> dict:
    body = {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": tool, "arguments": {"order_id": "ORD-10042"}}}
    r = httpx.post(RESOURCE, json=body, headers={**HDR, "Authorization": f"Bearer {tok}"})
    assert r.status_code == 200, (r.status_code, r.text)
    return r.json()["result"]


def post(tok: str | None = None, host: str | None = None) -> httpx.Response:
    h = dict(HDR)
    if tok: h["Authorization"] = f"Bearer {tok}"
    if host: h["Host"] = host
    return httpx.post(RESOURCE, json=INIT, headers=h)


r = post()
print("no token      ->", r.status_code, r.headers["www-authenticate"])
assert r.status_code == 401 and "resource_metadata=" in r.headers["www-authenticate"]

prm = httpx.get("http://127.0.0.1:8000/.well-known/oauth-protected-resource/mcp").json()
print("metadata      ->", prm)
assert prm["resource"] == RESOURCE and prm["authorization_servers"][0].rstrip("/") == ISSUER

for name, tok in {
    "wrong audience": token(aud="https://some-other-api.example.com"),
    "expired": token(exp=-120),
    "wrong issuer": token(iss="https://evil.example.com"),
    "rogue key": token(key=ROGUE),
    "alg none": jwt.encode({"iss": ISSUER, "aud": RESOURCE, "sub": "x", "exp": int(time.time()) + 300}, None, algorithm="none"),
}.items():
    r = post(tok)
    print(f"{name:14}->", r.status_code)
    assert r.status_code == 401, name

r = post(token(scope="profile"))
print("missing scope ->", r.status_code, r.headers["www-authenticate"])
assert r.status_code == 403 and "insufficient_scope" in r.headers["www-authenticate"]

r = post(token(), host="attacker.example.com")
print("foreign Host  ->", r.status_code)
assert r.status_code in (400, 421, 403)

assert post(token()).status_code == 200
ok = call("get_order_status", token())
print("read tool     ->", ok["isError"], ok["content"][0]["text"])
assert ok["isError"] is False

denied = call("cancel_order", token())                      # read-only token on a write tool
print("write, no scope->", denied["isError"], denied["content"][0]["text"])
assert denied["isError"] is True and "orders.write" in denied["content"][0]["text"]

done = call("cancel_order", token(scope="orders.read orders.write"))
print("write tool    ->", done["isError"], done["content"][0]["text"])
assert done["isError"] is False and "user-123" in done["content"][0]["text"]
print("ALL MCP AUTH TESTS OK")
