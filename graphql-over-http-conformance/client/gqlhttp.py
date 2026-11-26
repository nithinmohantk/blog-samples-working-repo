"""A GraphQL-over-HTTP client that reads responses the way the September 2026 edition says.

- Send Accept: application/graphql-response+json, application/json;q=0.9
- application/graphql-response+json: a GraphQL response, whatever the status code.
- application/json: a GraphQL response only when the status is 2xx (legacy servers).
- Anything else (a proxy's 502 page, a rate limiter's 429): a transport error.

Servers that never send application/graphql-response+json (legacy servers) often answer a
validation error with 400 and application/json. The spec says a client cannot know such a body
came from GraphQL, so by default it is a transport error. If you know every hop in front of the
server, trust_json_errors=True reads those bodies too, when they have the shape of a GraphQL result.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

GQL = "application/graphql-response+json"
JSON = "application/json"
ACCEPT = f"{GQL}, {JSON};q=0.9"


class TransportError(Exception):
    """The response did not come from a GraphQL server, or could not be read as one."""

    def __init__(self, status: int, content_type: str, message: str) -> None:
        super().__init__(f"HTTP {status} ({content_type or 'no content type'}): {message}")
        self.status = status
        self.content_type = content_type


@dataclass
class Result:
    data: dict[str, Any] | None
    errors: list[dict[str, Any]] = field(default_factory=list)
    extensions: dict[str, Any] | None = None
    status: int = 200

    @property
    def partial(self) -> bool:
        """Executed, with some fields failing: data and errors together (status 294 when the server follows the spec)."""
        return self.data is not None and bool(self.errors)

    @property
    def request_error(self) -> bool:
        """Not executed at all: parse, validation or variable errors."""
        return self.data is None and bool(self.errors)


class GraphQLHTTPClient:
    def __init__(self, url: str, client: httpx.Client | None = None, timeout: float = 10.0,
                 trust_json_errors: bool = False) -> None:
        self.url = url
        self._client = client or httpx.Client(timeout=timeout)
        self.trust_json_errors = trust_json_errors

    def execute(self, query: str, variables: dict[str, Any] | None = None,
                operation_name: str | None = None) -> Result:
        body: dict[str, Any] = {"query": query}
        if variables is not None:
            body["variables"] = variables
        if operation_name is not None:
            body["operationName"] = operation_name
        response = self._client.post(self.url, json=body, headers={"accept": ACCEPT})
        return self.read(response, self.trust_json_errors)

    @staticmethod
    def read(response: httpx.Response, trust_json_errors: bool = False) -> Result:
        media = response.headers.get("content-type", "").split(";")[0].strip().lower()
        status = response.status_code
        legacy_error = media == JSON and 400 <= status < 500 and trust_json_errors
        if media == GQL or (media == JSON and 200 <= status < 300) or legacy_error:
            try:
                payload = response.json()
            except ValueError as exc:
                raise TransportError(status, media, "body is not JSON") from exc
            if not isinstance(payload, dict) or ("data" not in payload and "errors" not in payload):
                raise TransportError(status, media, "body is not a GraphQL response")
            return Result(payload.get("data"), payload.get("errors") or [], payload.get("extensions"), status)
        raise TransportError(status, media, response.text[:200])
