import json

import httpx
import pytest

from gqlhttp import ACCEPT, GQL, GraphQLHTTPClient, TransportError


def client_returning(status: int, content_type: str | None, body: str, seen: list | None = None,
                     **options) -> GraphQLHTTPClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        headers = {"content-type": content_type} if content_type else {}
        return httpx.Response(status, headers=headers, content=body.encode())
    return GraphQLHTTPClient("http://test/graphql", httpx.Client(transport=httpx.MockTransport(handler)), **options)


def test_sends_accept_and_json_body():
    seen: list[httpx.Request] = []
    c = client_returning(200, GQL, '{"data":{"hello":"world"}}', seen)
    result = c.execute("query Q($id: ID!) { user(id: $id) { name } }", {"id": "1"}, "Q")
    assert result.data == {"hello": "world"}
    assert seen[0].headers["accept"] == ACCEPT
    assert seen[0].headers["content-type"] == "application/json"
    assert json.loads(seen[0].content) == {"query": "query Q($id: ID!) { user(id: $id) { name } }",
                                           "variables": {"id": "1"}, "operationName": "Q"}


def test_request_error_with_422_is_a_graphql_result():
    c = client_returning(422, f"{GQL}; charset=utf-8", '{"errors":[{"message":"Cannot query field"}]}')
    result = c.execute("{ nope }")
    assert result.request_error and result.status == 422


def test_partial_success_294():
    c = client_returning(294, GQL, '{"data":{"hello":"world","boom":null},"errors":[{"message":"boom failed","path":["boom"]}]}')
    result = c.execute("{ hello boom }")
    assert result.partial and result.data["hello"] == "world" and result.status == 294


def test_legacy_server_200_json():
    c = client_returning(200, "application/json", '{"data":null,"errors":[{"message":"Syntax Error"}]}')
    assert c.execute("{").request_error


@pytest.mark.parametrize("status,ctype,body", [
    (502, "text/html", "<html>Bad Gateway</html>"),
    (429, "application/json", '{"message":"rate limited"}'),
    (400, "application/json", '{"errors":[{"message":"looks like GraphQL"}]}'),
    (500, None, ""),
])
def test_non_graphql_responses_are_transport_errors(status, ctype, body):
    with pytest.raises(TransportError) as err:
        client_returning(status, ctype, body).execute("{ hello }")
    assert err.value.status == status


def test_graphql_media_type_with_garbage_body():
    with pytest.raises(TransportError, match="not JSON"):
        client_returning(200, GQL, "<html>").execute("{ hello }")


def test_json_that_is_not_a_graphql_response():
    with pytest.raises(TransportError, match="not a GraphQL response"):
        client_returning(200, "application/json", '{"status":"ok"}').execute("{ hello }")


def test_legacy_400_json_is_read_only_when_trusted():
    body = '{"errors":[{"message":"Cannot query field nope"}]}'
    with pytest.raises(TransportError):
        client_returning(400, "application/json", body).execute("{ nope }")
    result = client_returning(400, "application/json", body, trust_json_errors=True).execute("{ nope }")
    assert result.request_error and result.status == 400


def test_trusted_json_still_rejects_non_graphql_bodies():
    with pytest.raises(TransportError, match="not a GraphQL response"):
        client_returning(429, "application/json", '{"message":"slow down"}', trust_json_errors=True).execute("{ hello }")
