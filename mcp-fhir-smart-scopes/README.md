# An MCP server over FHIR, with tools mapped to SMART scopes

Sample for the dataa.dev article "[An MCP Server over FHIR: Which Tools to Expose and How SMART Scopes Map to Them](https://www.dataa.dev/2026/04/08/an-mcp-server-over-fhir-tools-and-smart-scopes/)".

Seven tools in front of a FHIR R4 server. What a caller may list and call is decided from the SMART v2
scopes and the patient context in its access token. Synthetic data only. Not clinically validated, and
not a medical device.

| Path | What it is |
| --- | --- |
| `smart/scopes.py` | Parser for SMART v2 scopes (and v1, translated), including granular `?category=` filters |
| `server/policy.py` | The decision for one tool call: scope, patient compartment, category filter. Pure functions |
| `server/tokens.py` | JWT verification (RS256, issuer, audience, expiry) and the token's SMART context |
| `server/fhir.py` | The FHIR calls the tools make, on the server's own connection |
| `server/app.py` | The MCP server: seven typed tools, a scope-filtered tool list, an audit line per call |
| `lab/generic_server.py` | One tool that takes any FHIR path, written twice (naive and guarded), to be measured |
| `lab/fhirstub.py` | An in-memory stand-in for a FHIR server, for local runs. Not a FHIR server |
| `lab/data.py` | Three invented patients with observations, medication requests and conditions |
| `lab/probes.py` | Eight token profiles, 39 calls with their expected outcome, 15 requests for the generic tools |
| `lab/judge.py` | Checks every answer for records outside the token's scopes, independently of the server |
| `lab/run.py` | Loads the data, starts both servers, asks as each token, writes the tables |
| `tests/run.py` | 24 unit tests for the parser, the policy and the judge |

## Run

    ./ci.sh out                       # Python 3.13 and Docker; runs the stand-in and HAPI FHIR
    python -m lab.run out             # the stand-in only, inside a virtual environment with requirements.txt

## What was verified

GitHub Actions, `ubuntu-latest`, Python 3.13: MCP Python SDK 1.27.0, protocol revision 2025-11-25,
PyJWT 2.12.1, HAPI FHIR `hapiproject/hapi:v8.0.0`, dependencies resolved as of 7 April 2026. Transcripts
and JSON for the latest run are on the `ci-results-mcp-fhir-smart-scopes` branch.

## What this does not show

- No model is involved. The lab calls the tools directly, as a model's client would.
- No authorization server runs. The lab signs its own tokens with a key generated for the run, and puts
  the patient context in a `patient` claim. A real authorization server may return it another way.
- The MCP server reaches the FHIR server on an open loopback connection. In a deployment that
  connection carries the MCP server's own credential, and the FHIR server is not reachable by callers.
- The guarded generic tool passed fifteen requests written by the same hand that wrote the guard.
  That is not evidence it is safe against requests nobody thought of.
- Only `category` filters on Observation are implemented. Other granular scopes are parsed and not enforced
  by the tools, which is safe only because no tool here touches the resources they would apply to.
- No consent, break-glass, or data-segmentation labels. No paging beyond one page of fifty.
- Synthetic data. Nothing here has been clinically validated.
