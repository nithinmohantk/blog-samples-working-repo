// Second opinion: graphql-http's own audit suite (serverAudits) against each server.
// The audits in graphql-http 1.23.1 predate the September 2026 edition, so they test
// the earlier draft's expectations (for example, 400 rather than 422).
import { serverAudits } from "graphql-http";

const servers = {
  "graphql-http": "http://127.0.0.1:4001/graphql",
  "GraphQL Yoga": "http://127.0.0.1:4002/graphql",
  "Apollo Server": "http://127.0.0.1:4003/graphql",
  Mercurius: "http://127.0.0.1:4004/graphql",
  Strawberry: "http://127.0.0.1:4005/graphql",
  Ariadne: "http://127.0.0.1:4006/graphql",
};

const rows = [];
for (const [name, url] of Object.entries(servers)) {
  const results = await Promise.all(serverAudits({ url }).map((audit) => audit.fn()));
  const count = (status) => results.filter((r) => r.status === status).length;
  rows.push({
    server: name,
    MUST_ok: results.filter((r) => r.status === "ok" && r.name.startsWith("MUST")).length,
    MUST_fail: results.filter((r) => r.status !== "ok" && r.name.startsWith("MUST")).length,
    SHOULD_ok: results.filter((r) => r.status === "ok" && r.name.startsWith("SHOULD")).length,
    SHOULD_fail: results.filter((r) => r.status !== "ok" && r.name.startsWith("SHOULD")).length,
    total: results.length,
    ok: count("ok"),
  });
  const failedMust = results.filter((r) => r.status !== "ok" && r.name.startsWith("MUST")).map((r) => `    ${r.name}`);
  if (failedMust.length) console.log(`${name} failed MUST audits:\n${failedMust.join("\n")}`);
}
console.table(rows);
