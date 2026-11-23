-- A short tour of PostgreSQL 19 in plain SQL. ci.sh runs it with psql -a, so the output file shows
-- each statement followed by what the server answered.
\pset footer off
create schema tour;
set search_path = tour;

-- 1. REPACK: rewrite a bloated table
create table invoice(id bigint primary key, customer_id int not null, body text not null);
insert into invoice select g, g % 5000, repeat('x', 200) from generate_series(1, 200000) g;
create index invoice_customer on invoice(customer_id);
delete from invoice where id % 3 <> 0;
select pg_size_pretty(pg_total_relation_size('invoice')) as size_before;

-- Readers and writers keep working while this runs. The table needs a primary key.
REPACK (CONCURRENTLY) invoice;
select pg_size_pretty(pg_total_relation_size('invoice')) as size_after;

-- Rewrite in the order of an index and refresh the statistics in the same pass.
-- This form takes an exclusive lock, as CLUSTER did.
REPACK (ANALYZE) invoice USING INDEX invoice_customer;

-- 2. Get or create in one statement
create table customer(
    id bigint generated always as identity primary key,
    email text not null unique,
    name text not null);

insert into customer(email, name) values ('ada@example.test', 'Ada')
on conflict (email) do select
returning id, name, old.id as old_id, new.id as new_id;

-- The same email again: nothing is written, and the existing row comes back.
insert into customer(email, name) values ('ada@example.test', 'Somebody else')
on conflict (email) do select
returning id, name, old.id as old_id, new.id as new_id;

-- Lock the row that was found, for a read-then-write in the same transaction.
begin;
insert into customer(email, name) values ('ada@example.test', 'x')
on conflict (email) do select for update
returning id, name;
commit;

-- 3. Carry the last known reading forward
select ts, reading, last_value(reading) ignore nulls over (order by ts) as carried
from (values (1, 20), (2, null), (3, null), (4, 23), (5, null)) as t(ts, reading);

-- 4. A query straight to a JSON array
copy (select id, email, name from customer) to stdout (format json, force_array);

-- 5. A random date in a range, for test data
select bool_and(d between date '2026-01-01' and date '2026-12-31') as all_in_range, count(distinct d) > 100 as varied
from (select random(date '2026-01-01', date '2026-12-31') as d from generate_series(1, 1000)) s;

-- 6. String methods inside a JSON path
select jsonb_path_query('{"name": "  Ada Lovelace  "}', '$.name.btrim().upper()') as name,
       jsonb_path_query('"2026-11-19"', '$.split_part("-", 1)') as year;

drop schema tour cascade;
