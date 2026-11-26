| Case | graphql-http 1.23.1 | GraphQL Yoga 6.1.1 | Apollo Server 5.5.2 | Mercurius 16.12.2 | Strawberry 0.341.3 | Ariadne 1.1.1 |
|---|---|---|---|---|---|---|
| A1 POST, Accept graphql-response+json | 200 gql ok | 200 gql ok | 200 gql ok | 200 json X | 200 json X | 200 json X |
| A2 POST, Accept application/json (legacy client) | 200 json ok | 200 json ok | 200 json ok | 200 json ok | 200 json ok | 200 json ok |
| A3 POST, Accept both, graphql-response+json preferred | 200 gql ok | 200 gql ok | 200 gql ok | 200 json X | 200 json X | 200 json X |
| A4 POST, no Accept header | 200 json . | 200 json . | 200 json . | 200 json . | 200 json . | 200 json . |
| A5 POST, Accept text/html only | 406 - ok | 406 - ok | 406 json ok | 200 json ~ | 200 json ~ | 200 json ~ |
| B1 POST, Content-Type text/plain | 415 - ok | 415 - ok | 400 gql ~ | 400 json ~ | 400 text/plain ~ | 400 text/plain ~ |
| B2 POST, no Content-Type | 415 - ok | 415 - ok | 400 gql ok | 415 json ok | 400 text/plain ok | 400 text/plain ok |
| B3 POST, body is not JSON | 400 json ok | 400 gql ok | 400 text/html ok | 400 json ok | 400 text/plain ok | 400 text/plain ok |
| B4 POST, misspelt parameter (qeury) | 400 json ~ | 400 gql ~ | 400 gql ~ | 400 json ~ | 400 text/plain ~ | 400 json ~ |
| B5 POST, variables is an array | 400 json ~ | 400 gql ~ | 400 gql ~ | 400 json ~ | 400 text/plain ~ | 400 json ~ |
| B6 POST, unknown top-level property | 200 gql ok | 400 gql X | 200 gql ok | 200 json ok | 200 json ok | 200 json ok |
| C1 Document does not parse | 400 gql ok | 400 gql ok | 400 gql ok | 400 json ok | 200 json ~ | 400 json ok |
| C2 Validation error (unknown field) | 400 gql ~ | 400 gql ~ | 400 gql ~ | 400 json ~ | 200 json ~ | 400 json ~ |
| C3 Two operations, no operationName | 400 gql ~ | 400 gql ~ | 400 gql ~ | 200 json ~ | 200 json ~ | 400 json ~ |
| C4 Required variable missing | 200 gql X | 400 gql ~ | 400 gql ~ | 200 json ~ | 200 json ~ | 400 json ~ |
| C5 Partial result (data and errors) | 200 gql ~ | 200 gql ~ | 200 gql ~ | 200 json ~ | 200 json ~ | 200 json ~ |
| C6 Validation error, legacy Accept application/json | 200 json ~ | 200 json ~ | 400 json ~ | 400 json ~ | 200 json ~ | 400 json ~ |
| D1 GET query | 200 gql ok | 200 gql ok | 400 gql . | 200 json ok | 200 json ok | 200 text/html . |
| D2 GET mutation | 405 - ok | 405 gql ok | 400 gql ~ | 405 json X | 400 text/plain ~ | 200 text/html . |
| D3 PUT | 405 - ok | 405 gql ok | 405 gql ok | 404 json ~ | 405 text/plain ok | 405 - ok |
| D4 GET query + apollo-require-preflight | 200 gql ok | 200 gql ok | 200 gql ok | 200 json ok | 200 json ok | 200 text/html . |
| D5 GET mutation + apollo-require-preflight | 405 - ok | 405 gql ok | 405 gql ok | 405 json X | 400 text/plain ~ | 200 text/html . |
| **MUST violations / SHOULD differences** | 1 / 6 | 1 / 7 | 0 / 9 | 4 / 10 | 2 / 12 | 2 / 9 |

ok = as the spec says, ~ = allowed but not what the spec recommends (SHOULD), X = breaks a MUST, . = left open by the spec. gql = application/graphql-response+json

graphql-http 1.23.1
  B4: spec: 422
  B5: spec: 422
  C2: spec: 422
  C3: spec: 422
  C4: spec: 422; 200 for a result without data (spec: 4xx or 5xx)
  C5: 200: allowed (2xx), status-code section recommends 294
  C6: spec: 422

GraphQL Yoga 6.1.1
  B4: spec: 422
  B5: spec: 422
  B6: spec: 200
  C2: spec: 422
  C3: spec: 422
  C4: spec: 422
  C5: 200: allowed (2xx), status-code section recommends 294
  C6: spec: 422

Apollo Server 5.5.2
  B1: spec: 415
  B4: spec: 422
  B5: spec: 422
  C2: spec: 422
  C3: spec: 422
  C4: spec: 422
  C5: 200: allowed (2xx), status-code section recommends 294
  C6: spec: 422
  D2: spec: 405

Mercurius 16.12.2
  A1: spec: application/graphql-response+json
  A3: spec: application/graphql-response+json
  A5: ignored Accept (allowed), spec recommends 406
  B1: spec: 415
  B4: spec: 422
  B5: spec: 422
  C2: spec: 422
  C3: spec: 422
  C4: spec: 422
  C5: 200: allowed (2xx), status-code section recommends 294
  C6: spec: 422
  D2: 405 without Allow header (RFC 9110)
  D3: spec: 405
  D5: 405 without Allow header (RFC 9110)

Strawberry 0.341.3
  A1: spec: application/graphql-response+json
  A3: spec: application/graphql-response+json
  A5: ignored Accept (allowed), spec recommends 406
  B1: spec: 415
  B4: spec: 422
  B5: spec: 422
  C1: spec: 400
  C2: spec: 422
  C3: spec: 422
  C4: spec: 422
  C5: 200: allowed (2xx), status-code section recommends 294
  C6: spec: 422
  D2: spec: 405
  D5: spec: 405

Ariadne 1.1.1
  A1: spec: application/graphql-response+json
  A3: spec: application/graphql-response+json
  A5: ignored Accept (allowed), spec recommends 406
  B1: spec: 415
  B4: spec: 422
  B5: spec: 422
  C2: spec: 422
  C3: spec: 422
  C4: spec: 422
  C5: 200: allowed (2xx), status-code section recommends 294
  C6: spec: 422
