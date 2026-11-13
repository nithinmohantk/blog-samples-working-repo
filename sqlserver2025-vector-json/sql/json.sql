-- T-SQL for the JSON experiments. The lab program runs each named block as one batch.

-- name: json.tables
-- The same documents four ways.
CREATE TABLE dbo.OrdersN (id int NOT NULL CONSTRAINT PK_OrdersN PRIMARY KEY CLUSTERED, doc nvarchar(max) NOT NULL CONSTRAINT CK_OrdersN_json CHECK (ISJSON(doc) = 1));
CREATE TABLE dbo.OrdersV (id int NOT NULL CONSTRAINT PK_OrdersV PRIMARY KEY CLUSTERED, doc varchar(max) COLLATE Latin1_General_100_BIN2_UTF8 NOT NULL);
CREATE TABLE dbo.OrdersJ (id int NOT NULL CONSTRAINT PK_OrdersJ PRIMARY KEY CLUSTERED, doc json NOT NULL);
CREATE TABLE dbo.OrdersC (id int NOT NULL CONSTRAINT PK_OrdersC PRIMARY KEY CLUSTERED, doc json NOT NULL);

-- name: json.load
INSERT INTO dbo.OrdersN (id, doc)
SELECT CAST(JSON_VALUE(value, '$.orderId') AS int), value
FROM OPENJSON(@rows);

-- name: json.copy
INSERT INTO dbo.OrdersV (id, doc) SELECT id, doc FROM dbo.OrdersN;
INSERT INTO dbo.OrdersJ (id, doc) SELECT id, doc FROM dbo.OrdersN;
INSERT INTO dbo.OrdersC (id, doc) SELECT id, doc FROM dbo.OrdersN;

-- name: json.size
SELECT SUM(used_page_count) * 8 AS kb
FROM sys.dm_db_partition_stats
WHERE object_id = OBJECT_ID(@table);

-- name: json.query.text
SELECT COUNT(*) AS orders, SUM(CAST(JSON_VALUE(doc, '$.total') AS decimal(12, 2))) AS total
FROM dbo.OrdersN
WHERE JSON_VALUE(doc, '$.customer.country') = N'MT';

-- name: json.query.native
SELECT COUNT(*) AS orders, SUM(CAST(JSON_VALUE(doc, '$.total') AS decimal(12, 2))) AS total
FROM dbo.OrdersJ
WHERE JSON_VALUE(doc, '$.customer.country') = N'MT';

-- name: json.computed
-- The long-standing way to index a property: a computed column and an ordinary index.
ALTER TABLE dbo.OrdersC ADD country AS CAST(JSON_VALUE(doc, '$.customer.country') AS nchar(2));
CREATE INDEX IX_OrdersC_country ON dbo.OrdersC (country);

-- name: json.query.computed
SELECT COUNT(*) AS orders, SUM(CAST(JSON_VALUE(doc, '$.total') AS decimal(12, 2))) AS total
FROM dbo.OrdersC
WHERE country = N'MT';

-- name: json.index
CREATE JSON INDEX IX_OrdersJ_doc ON dbo.OrdersJ (doc) FOR ('$.customer.country', '$.status');

-- name: json.query.contains
SELECT COUNT(*) AS orders, SUM(CAST(JSON_VALUE(doc, '$.total') AS decimal(12, 2))) AS total
FROM dbo.OrdersJ
WHERE JSON_CONTAINS(doc, 'MT', '$.customer.country') = 1;

-- name: json.query.hinted
SELECT COUNT(*) AS orders, SUM(CAST(JSON_VALUE(doc, '$.total') AS decimal(12, 2))) AS total
FROM dbo.OrdersJ WITH (INDEX (IX_OrdersJ_doc))
WHERE JSON_VALUE(doc, '$.customer.country') = N'MT';

-- name: json.rebuild
-- Compact every table after the updates, so the lookups that follow compare like with like.
ALTER INDEX ALL ON dbo.OrdersN REBUILD;
ALTER INDEX ALL ON dbo.OrdersJ REBUILD;
ALTER INDEX ALL ON dbo.OrdersC REBUILD;

-- name: json.modify.native
-- Inside a transaction, so the log written by this one statement can be read before it commits.
BEGIN TRANSACTION;
UPDATE dbo.OrdersJ SET doc.modify('$.status', @status);
SELECT database_transaction_log_bytes_used
FROM sys.dm_tran_database_transactions
WHERE database_id = DB_ID() AND transaction_id = CURRENT_TRANSACTION_ID();
COMMIT;

-- name: json.modify.function
BEGIN TRANSACTION;
UPDATE dbo.OrdersC SET doc = JSON_MODIFY(doc, '$.status', @status);
SELECT database_transaction_log_bytes_used
FROM sys.dm_tran_database_transactions
WHERE database_id = DB_ID() AND transaction_id = CURRENT_TRANSACTION_ID();
COMMIT;

-- name: json.modify.text
BEGIN TRANSACTION;
UPDATE dbo.OrdersN SET doc = JSON_MODIFY(doc, '$.status', @status);
SELECT database_transaction_log_bytes_used
FROM sys.dm_tran_database_transactions
WHERE database_id = DB_ID() AND transaction_id = CURRENT_TRANSACTION_ID();
COMMIT;

-- name: json.aggregate
-- Orders per country as one JSON object, and one customer's order numbers as an array.
SELECT CAST(JSON_OBJECTAGG(country : orders) AS nvarchar(max)) AS per_country
FROM (SELECT TOP (5) JSON_VALUE(doc, '$.customer.country') AS country, COUNT(*) AS orders
      FROM dbo.OrdersJ
      GROUP BY JSON_VALUE(doc, '$.customer.country')
      ORDER BY COUNT(*) DESC) AS c;

-- name: json.shred
-- Order lines as rows.
SELECT TOP (3) o.id, l.sku, l.qty, l.price
FROM dbo.OrdersJ AS o
CROSS APPLY OPENJSON(o.doc, '$.lines') WITH (sku varchar(12), qty int, price decimal(9, 2)) AS l
WHERE o.id = 42
ORDER BY l.sku;
