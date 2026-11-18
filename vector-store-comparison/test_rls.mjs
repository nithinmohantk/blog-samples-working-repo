// Runs pgvector_rls.sql in an in-process PostgreSQL (PGlite) with the pgvector extension.
import { readFileSync } from "node:fs";
import assert from "node:assert/strict";
import { PGlite } from "@electric-sql/pglite";
import { vector } from "@electric-sql/pglite-pgvector";

const db = new PGlite({ extensions: { vector } });
await db.exec(readFileSync("pgvector_rls.sql", "utf8"));

const vec = (seed) => "[" + Array.from({ length: 1024 }, (_, i) => Math.sin(seed + i).toFixed(5)).join(",") + "]";
const asTenant = async (tenant, fn) => db.transaction(async (tx) => {
  await tx.exec("SET LOCAL ROLE rag_app");
  await tx.query("SELECT set_config('app.tenant_id', $1, true)", [tenant]);   // scoped to this transaction
  return fn(tx);
});
const search = (tx) => tx.query(
  "SELECT tenant_id, doc_id FROM chunks ORDER BY embedding <=> $1::vector LIMIT 5", [vec(1)]);

await asTenant("acme", (tx) => tx.query(
  "INSERT INTO chunks (tenant_id, doc_id, content, embedding) VALUES ('acme','a-1','alpha',$1::vector)", [vec(1)]));
await asTenant("globex", (tx) => tx.query(
  "INSERT INTO chunks (tenant_id, doc_id, content, embedding) VALUES ('globex','g-1','gamma',$1::vector)", [vec(1.01)]));

const acme = await asTenant("acme", search);
console.log("acme sees   ->", acme.rows);
assert.deepEqual(acme.rows, [{ tenant_id: "acme", doc_id: "a-1" }]);

const globex = await asTenant("globex", search);
console.log("globex sees ->", globex.rows);
assert.deepEqual(globex.rows, [{ tenant_id: "globex", doc_id: "g-1" }]);

const none = await db.transaction(async (tx) => { await tx.exec("SET LOCAL ROLE rag_app"); return search(tx); });
console.log("no tenant   ->", none.rows);
assert.equal(none.rows.length, 0);                      // fails closed when the setting is missing

await assert.rejects(asTenant("acme", (tx) => tx.query(
  "INSERT INTO chunks (tenant_id, doc_id, content, embedding) VALUES ('globex','x','forged',$1::vector)", [vec(2)])));
console.log("cross-tenant insert -> rejected");

const ext = await db.query("SELECT extversion FROM pg_extension WHERE extname='vector'");
const ver = await db.query("SHOW server_version");
console.log("pgvector", ext.rows[0].extversion, "on PostgreSQL", ver.rows[0].server_version);
console.log("ALL RLS TESTS OK");
