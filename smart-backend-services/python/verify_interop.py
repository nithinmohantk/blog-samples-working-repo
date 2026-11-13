"""A second client, in another language, against the same token endpoint and gateway.

    python verify_interop.py <fhir base> <client id> <private key PEM> <key id> <server JWKS URL>

It builds its assertion with PyJWT and signs with RS384, so the .NET token endpoint verifies a signature made by
a different library; and it verifies the ES384 access token the .NET server issued, with PyJWT. Nothing here
shares code with the C# client.
"""
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

import jwt

fhir_base, client_id, key_file, key_id, jwks_url = sys.argv[1:6]
private_key = open(key_file, encoding="ascii").read()
passed = failed = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global passed, failed
    passed, failed = passed + bool(condition), failed + (not condition)
    print(f"{'ok  ' if condition else 'FAIL'}  {name}{'' if condition or not detail else f'  [{detail}]'}")


def call(url: str, data: dict | None = None, token: str | None = None) -> tuple[int, dict]:
    headers = {"Accept": "application/json"} | ({"Authorization": f"Bearer {token}"} if token else {})
    request = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode() if data else None, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        body = error.read().decode()
        return error.code, json.loads(body) if body.startswith("{") else {}


def assertion(token_endpoint: str, lifetime: int = 120) -> str:
    claims = {"iss": client_id, "sub": client_id, "aud": token_endpoint, "exp": int(time.time()) + lifetime, "jti": uuid.uuid4().hex}
    return jwt.encode(claims, private_key, algorithm="RS384", headers={"kid": key_id, "typ": "JWT"})


def token_request(token_endpoint: str, client_assertion: str, scope: str = "system/Patient.rs") -> tuple[int, dict]:
    return call(token_endpoint, {"grant_type": "client_credentials", "scope": scope,
                                 "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer", "client_assertion": client_assertion})


status, configuration = call(fhir_base + ".well-known/smart-configuration")
token_endpoint = configuration.get("token_endpoint", "")
check("discovery offers private_key_jwt with RS384", status == 200 and "private_key_jwt" in configuration.get("token_endpoint_auth_methods_supported", [])
      and "RS384" in configuration.get("token_endpoint_auth_signing_alg_values_supported", []))

first = assertion(token_endpoint)
status, granted = token_request(token_endpoint, first)
check("an RS384 assertion built with PyJWT is accepted by the .NET token endpoint", status == 200 and granted.get("token_type") == "bearer" and granted.get("scope") == "system/Patient.rs", str(status))
access_token = granted.get("access_token", "")

signing_key = jwt.PyJWKClient(jwks_url).get_signing_key_from_jwt(access_token)
claims = jwt.decode(access_token, signing_key.key, algorithms=["ES384"], audience=fhir_base)
check("the ES384 access token issued by .NET verifies with PyJWT against the server's published key", claims["client_id"] == client_id and claims["scope"] == "system/Patient.rs" and claims["exp"] - claims["iat"] == 300)

status, bundle = call(fhir_base + "Patient?_count=1", token=access_token)
check("the token reads patients through the gateway", status == 200 and bundle.get("resourceType") == "Bundle", str(status))
status, outcome = call(fhir_base + "Observation?_count=1", token=access_token)
check("the same token is refused for observations", status == 403 and outcome.get("resourceType") == "OperationOutcome", str(status))

status, refused = token_request(token_endpoint, first)
check("the same assertion a second time is refused as invalid_client, with no description", status == 401 and refused == {"error": "invalid_client"}, json.dumps(refused))
status, refused = token_request(token_endpoint, assertion(token_endpoint, lifetime=600))
check("an assertion valid for ten minutes is refused", status == 401 and refused.get("error") == "invalid_client", json.dumps(refused))
status, refused = token_request(token_endpoint, assertion(token_endpoint), scope="system/*.cruds")
check("a request for every resource type is refused for a client registered for patients only", status == 400 and refused.get("error") == "invalid_scope", json.dumps(refused))

print(f"{passed} of {passed + failed} checks passed")
sys.exit(0 if failed == 0 else 1)
