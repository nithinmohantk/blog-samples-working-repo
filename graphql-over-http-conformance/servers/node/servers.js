// Starts four Node GraphQL servers with their default HTTP settings.
//   node servers.js        -> graphql-http :4001, Yoga :4002, Apollo :4003, Mercurius :4004
import http from "node:http";
import { buildSchema } from "graphql";
import { createHandler } from "graphql-http/lib/use/http";
import { createSchema, createYoga } from "graphql-yoga";
import { ApolloServer } from "@apollo/server";
import { startStandaloneServer } from "@apollo/server/standalone";
import Fastify from "fastify";
import mercurius from "mercurius";
import { typeDefs, resolvers, rootValue } from "./schema.js";

const started = [];

// 1. graphql-http: the reference implementation maintained in the GraphQL org.
const handler = createHandler({ schema: buildSchema(typeDefs), rootValue });
const ref = http.createServer((req, res) => {
  if (req.url.startsWith("/graphql")) return handler(req, res);
  res.writeHead(404).end();
});
await new Promise((ok) => ref.listen(4001, "127.0.0.1", ok));
started.push("graphql-http :4001/graphql");

// 2. GraphQL Yoga.
const yoga = createYoga({ schema: createSchema({ typeDefs, resolvers }), logging: false });
await new Promise((ok) => http.createServer(yoga).listen(4002, "127.0.0.1", ok));
started.push("graphql-yoga :4002/graphql");

// 3. Apollo Server with its standalone HTTP server (it answers on every path).
const apollo = new ApolloServer({ typeDefs, resolvers });
await startStandaloneServer(apollo, { listen: { port: 4003, host: "127.0.0.1" } });
started.push("@apollo/server :4003/graphql");

// 4. Mercurius on Fastify.
const fastify = Fastify({ logger: false });
await fastify.register(mercurius, { schema: typeDefs, resolvers });
await fastify.listen({ port: 4004, host: "127.0.0.1" });
started.push("mercurius :4004/graphql");

console.log("listening:", started.join(", "));
