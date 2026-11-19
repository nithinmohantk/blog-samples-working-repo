-- Run against the SOURCE PostgreSQL database (12 or later) before planning a
-- move to Aurora DSQL. Lists objects that Aurora DSQL did not support in
-- February 2026, plus tables that exceed its documented per-table limits.
-- Read-only: it queries the system catalogs and changes nothing.
WITH user_ns AS (
    SELECT oid, nspname FROM pg_namespace
    WHERE nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
      AND nspname NOT LIKE 'pg_temp_%' AND nspname NOT LIKE 'pg_toast_temp_%'
),
ext_objects AS (
    SELECT objid FROM pg_depend WHERE deptype = 'e'
)
SELECT 'trigger' AS category,
       n.nspname || '.' || c.relname || ': ' || t.tgname AS object,
       'move the logic into the application or an event consumer' AS action
FROM pg_trigger t
JOIN pg_class c ON c.oid = t.tgrelid
JOIN user_ns n ON n.oid = c.relnamespace
WHERE NOT t.tgisinternal

UNION ALL
SELECT 'procedural function',
       n.nspname || '.' || p.proname || ' (' || l.lanname || ')',
       'rewrite as a SQL function or move into the application'
FROM pg_proc p
JOIN pg_language l ON l.oid = p.prolang
JOIN user_ns n ON n.oid = p.pronamespace
WHERE l.lanname NOT IN ('sql', 'internal')
  AND p.oid NOT IN (SELECT objid FROM ext_objects)

UNION ALL
SELECT 'sequence or identity',
       n.nspname || '.' || c.relname,
       'use UUID keys or application-generated IDs'
FROM pg_class c
JOIN user_ns n ON n.oid = c.relnamespace
WHERE c.relkind = 'S'
  AND c.oid NOT IN (SELECT objid FROM ext_objects)

UNION ALL
SELECT 'foreign key',
       n.nspname || '.' || c.relname || ': ' || k.conname,
       'enforce the reference in the application'
FROM pg_constraint k
JOIN pg_class c ON c.oid = k.conrelid
JOIN user_ns n ON n.oid = c.relnamespace
WHERE k.contype = 'f'

UNION ALL
SELECT 'extension', e.extname || ' ' || e.extversion, 'remove the dependency'
FROM pg_extension e
WHERE e.extname <> 'plpgsql'

UNION ALL
SELECT 'too many indexes',
       n.nspname || '.' || c.relname || ' (' || count(*) || ' indexes)',
       'Aurora DSQL allows at most 24 indexes per table'
FROM pg_index i
JOIN pg_class c ON c.oid = i.indrelid
JOIN user_ns n ON n.oid = c.relnamespace
GROUP BY n.nspname, c.relname
HAVING count(*) > 24

UNION ALL
SELECT 'too many columns',
       n.nspname || '.' || c.relname || ' (' || count(*) || ' columns)',
       'Aurora DSQL allows at most 255 columns per table'
FROM pg_attribute a
JOIN pg_class c ON c.oid = a.attrelid AND c.relkind IN ('r', 'p')
JOIN user_ns n ON n.oid = c.relnamespace
WHERE a.attnum > 0 AND NOT a.attisdropped
GROUP BY n.nspname, c.relname
HAVING count(*) > 255

ORDER BY 1, 2;
