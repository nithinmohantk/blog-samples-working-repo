// The same small schema for every server, so only the HTTP layer differs.
// `boom` always throws: asking for it with `hello` gives a partial result
// (data and errors), which is what the spec's 294 status code is for.
export const typeDefs = /* GraphQL */ `
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
`;

export const resolvers = {
  Query: {
    hello: () => "world",
    user: (_parent, { id }) => ({ id, name: "Ada" }),
    boom: () => {
      throw new Error("boom failed");
    },
  },
  Mutation: {
    setGreeting: (_parent, { text }) => text,
  },
};

// graphql-http's reference handler takes a schema and a root value instead of
// resolver maps; these have the same behaviour.
export const rootValue = {
  hello: () => "world",
  user: ({ id }) => ({ id, name: "Ada" }),
  boom: () => {
    throw new Error("boom failed");
  },
  setGreeting: ({ text }) => text,
};
