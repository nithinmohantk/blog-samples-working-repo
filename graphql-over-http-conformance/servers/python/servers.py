"""Strawberry (:4005) and Ariadne (:4006) with their default ASGI apps and the same schema."""
import asyncio

import strawberry
import uvicorn
from ariadne import MutationType, QueryType, make_executable_schema
from ariadne.asgi import GraphQL as AriadneGraphQL
from strawberry.asgi import GraphQL as StrawberryGraphQL

TYPE_DEFS = """
type Query {
  hello: String!
  user(id: ID!): User
  boom: String
}
type User {
  id: ID!
  name: String!
}
type Mutation {
  setGreeting(text: String!): String!
}
"""


@strawberry.type
class User:
    id: strawberry.ID
    name: str


@strawberry.type
class Query:
    @strawberry.field
    def hello(self) -> str:
        return "world"

    @strawberry.field
    def user(self, id: strawberry.ID) -> User | None:
        return User(id=id, name="Ada")

    @strawberry.field
    def boom(self) -> str | None:
        raise ValueError("boom failed")


@strawberry.type
class Mutation:
    @strawberry.mutation(name="setGreeting")
    def set_greeting(self, text: str) -> str:
        return text


query, mutation = QueryType(), MutationType()
query.set_field("hello", lambda *_: "world")
query.set_field("user", lambda *_, id: {"id": id, "name": "Ada"})


@query.field("boom")
def resolve_boom(*_):
    raise ValueError("boom failed")


mutation.set_field("setGreeting", lambda *_, text: text)

# Both ASGI apps answer on any path, like Apollo's standalone server; the probe uses /graphql.
strawberry_app = StrawberryGraphQL(strawberry.Schema(Query, Mutation))
ariadne_app = AriadneGraphQL(make_executable_schema(TYPE_DEFS, query, mutation))


async def main() -> None:
    servers = [
        uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
        for app, port in ((strawberry_app, 4005), (ariadne_app, 4006))
    ]
    print("listening: strawberry :4005/graphql, ariadne :4006/graphql", flush=True)
    await asyncio.gather(*(s.serve() for s in servers))


if __name__ == "__main__":
    asyncio.run(main())
