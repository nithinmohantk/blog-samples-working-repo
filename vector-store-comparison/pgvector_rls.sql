-- pgvector_rls.sql - pooled multi-tenancy on Aurora PostgreSQL: one table, row-level security.
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE chunks (
    id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id  text        NOT NULL,
    doc_id     text        NOT NULL,
    content    text        NOT NULL,
    embedding  vector(1024) NOT NULL
);

CREATE INDEX chunks_tenant_idx ON chunks (tenant_id);
CREATE INDEX chunks_embedding_idx ON chunks USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- Every query is filtered by the tenant held in the session, whatever SQL the application sends.
ALTER TABLE chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE chunks FORCE ROW LEVEL SECURITY;          -- applies to the table owner as well

CREATE POLICY tenant_isolation ON chunks
    USING      (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

-- The application connects as a role that cannot bypass the policy.
CREATE ROLE rag_app NOLOGIN NOBYPASSRLS;
GRANT SELECT, INSERT, DELETE ON chunks TO rag_app;
