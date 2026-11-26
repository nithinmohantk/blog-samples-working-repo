# GraphQL over HTTP, September 2026 edition: six servers tested

Sample for the dataa.dev article on the first edition of the GraphQL over HTTP specification
(https://http-spec.graphql.org/September2026/). Six servers run the same schema with their
default settings; a probe sends the same 22 requests to each and compares the answers with the
specification. A small client shows how to read responses the way the specification intends.

| Path | What it is |
| --- | --- |
| `servers/node/servers.js` | graphql-http 1.23.1 (:4001), GraphQL Yoga 6.1.1 (:4002), Apollo Server 5.5.2 (:4003), Mercurius 16.12.2 on Fastify 5.12.8 (:4004), all on graphql 16.15.0 |
| `servers/node/schema.js` | The shared schema; `boom` always throws, to produce a partial result |
| `servers/python/servers.py` | Strawberry 0.341.3 (:4005) and Ariadne 1.1.1 (:4006) on uvicorn |
| `probe/probe.py` | The 22 requests and the rules each answer is checked against |
| `servers/node/audit.js` | graphql-http's own `serverAudits` as a second opinion |
| `client/gqlhttp.py` | Client that decides by media type, then status code; 12 tests |
| `results/` | Output of the run used in the article |

## Run it

```bash
./run.sh    # Node 22+, Python 3.12+; installs the pinned versions, runs everything, stops the servers
```

Versions are the newest stable releases published before 24 November 2026
(`npm install --before`, `uv pip install --exclude-newer`).

## Reading the probe table

`ok` = what the specification says; `~` = allowed, but the specification recommends something
else (a SHOULD); `X` = breaks a MUST; `.` = left open. `gql` is
`application/graphql-response+json`, `json` is `application/json`.

## What was verified

The run in `results/` was made on 26 November 2026 on Linux with Node 22.23.5 and Python 3.13.18,
all servers on 127.0.0.1. Hot Chocolate, graphql-java and gqlgen were not tested: their package
registries were not reachable from the test environment.
