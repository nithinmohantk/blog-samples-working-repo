-- T-SQL for the vector experiments. The lab program runs each named block as one batch.

-- name: vector.table
CREATE TABLE dbo.Doc
(
    id        int           NOT NULL CONSTRAINT PK_Doc PRIMARY KEY CLUSTERED,
    category  tinyint       NOT NULL,
    title     nvarchar(100) NOT NULL,
    embedding vector(384)   NOT NULL
);

-- name: vector.load
-- One round trip per thousand rows. The vectors arrive as JSON arrays inside one JSON document.
INSERT INTO dbo.Doc (id, category, title, embedding)
SELECT id, category, title, CAST(embedding AS vector(384))
FROM OPENJSON(@rows)
     WITH (id int, category tinyint, title nvarchar(100), embedding nvarchar(max) AS JSON);

-- name: vector.exact
-- Exact nearest neighbours: every row is read and its distance computed.
DECLARE @v vector(384) = CAST(@q AS vector(384));
SELECT TOP (10) id, VECTOR_DISTANCE('cosine', embedding, @v) AS distance
FROM dbo.Doc
ORDER BY distance;

-- name: vector.exact.filtered
DECLARE @v vector(384) = CAST(@q AS vector(384));
SELECT TOP (10) id, VECTOR_DISTANCE('cosine', embedding, @v) AS distance
FROM dbo.Doc
WHERE category = @category
ORDER BY distance;

-- name: vector.index
CREATE VECTOR INDEX IX_Doc_embedding ON dbo.Doc (embedding)
WITH (METRIC = 'cosine', TYPE = 'DiskANN');

-- name: vector.search
-- Approximate nearest neighbours through the vector index.
DECLARE @v vector(384) = CAST(@q AS vector(384));
SELECT t.id, s.distance
FROM VECTOR_SEARCH(
         TABLE = dbo.Doc AS t,
         COLUMN = embedding,
         SIMILAR_TO = @v,
         METRIC = 'cosine',
         TOP_N = 10) AS s
ORDER BY s.distance;

-- name: vector.search.filtered
-- The filter is applied to the ten rows the index returned, not before the search.
DECLARE @v vector(384) = CAST(@q AS vector(384));
SELECT t.id, s.distance
FROM VECTOR_SEARCH(
         TABLE = dbo.Doc AS t,
         COLUMN = embedding,
         SIMILAR_TO = @v,
         METRIC = 'cosine',
         TOP_N = 10) AS s
WHERE t.category = @category
ORDER BY s.distance;

-- name: vector.drop.index
DROP INDEX IX_Doc_embedding ON dbo.Doc;
