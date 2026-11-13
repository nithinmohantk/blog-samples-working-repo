# SMART Backend Services in .NET 10

Sample for the dataa.dev article "[SMART Backend Services: System-to-System FHIR Authorization in .NET 10](https://www.dataa.dev/2026/03/28/smart-backend-services-system-to-system-fhir-authorization-in-dotnet-10/)".

Three parts, following SMART App Launch 2.2.0: a client that authenticates with a signed JWT assertion, a token
endpoint that verifies it and issues a five-minute access token, and a gateway that enforces SMART v2 system
scopes in front of a FHIR server that knows nothing about SMART. No package references: signatures use the RSA
and ECDSA primitives in .NET, and the web parts use the ASP.NET Core shared framework.

Keys are generated when the tests start and exist only in memory. Nothing in this repository is a secret. All
data is synthetic. The token endpoint here is a teaching implementation: in production that role belongs to
your identity platform, and the checks listed in the article are what to verify it performs.

| Path | What it is |
| --- | --- |
| `src/Smart.Backend.Client/Jose.cs` | RS384 and ES384 signing and verification, JWK export and import, RFC 7638 thumbprints |
| `src/Smart.Backend.Client/SmartBackendClient.cs` | Discovery, the client assertion, a single-flight token cache, and a handler that sends the token only to the FHIR base |
| `src/Smart.Backend.Server/TokenService.cs` | The token endpoint's checks, the JWK Set cache, and the access tokens |
| `src/Smart.Backend.Server/ScopeSet.cs` | SMART v2 system scopes: parsing, and granting within a registration |
| `src/Smart.Backend.Server/FhirRequestClassifier.cs` | What a FHIR request needs, including `_include`, `_revinclude`, `_has`, chains and Bundles |
| `src/Smart.Backend.Server/FhirGateway.cs` | Token check, scope check, forwarding, address rewriting and page tokens |
| `tests/SelfTest` | All scenarios, against an in-memory stand-in or a real FHIR server |
| `python/verify_interop.py` | A second client written with PyJWT |
| `ci.sh` | Runs all of it |

## Run

    dotnet run --project tests/SelfTest -c Release -- out
    docker run -d -p 127.0.0.1:8083:8080 hapiproject/hapi:v8.0.0
    pip install PyJWT==2.12.1 cryptography==46.0.6
    dotnet run --project tests/SelfTest -c Release -- out http://127.0.0.1:8083/fhir python/verify_interop.py

The test host listens on 127.0.0.1 ports 5590 (token endpoint and gateway), 5591 (stand-in) and 5592 (a client's
key set). Everything is plain HTTP on loopback. The specification requires TLS 1.2 or later for every exchange,
and the client refuses a non-loopback address that is not https.

## What was verified

GitHub Actions, `ubuntu-latest`, .NET SDK 10.0.201 (runtime 10.0.5) installed into a private directory, HAPI FHIR
8.0.0 in Docker, Python 3.13 with PyJWT 2.12.1 and cryptography 46.0.6. Outputs of the latest run are on the
`ci-results-smart` branch under `smart-backend-services/`.

| Check | Result |
| --- | --- |
| All scenarios with the in-memory stand-in behind the gateway | 48 of 48 |
| All scenarios with HAPI FHIR behind the gateway, plus the Python client | 49 of 49 |
| Python client's own checks (RS384 assertion accepted by .NET; .NET ES384 token verified by PyJWT) | 8 of 8 |
| Scan of the published outputs for a private key or a token | none found |

Covered: 12 scope requests; 26 request shapes; 22 token requests that must be refused; key rotation through a JWK
Set URL; 20 gateway checks including `_revinclude`, `_has`, chained search, transactions and paging; token reuse
under concurrency, renewal before expiry, and recovery after a server restart.

## Not covered

TLS and mutual TLS, sender-constrained tokens (DPoP), token introspection and revocation, fine-grained scopes with
search parameters, v1 scope syntax, Bulk Data export, search by POST, FHIR operations, GraphQL, more than one
instance of the token endpoint (the replay cache is in memory), and any FHIR server other than HAPI.
