-- Puts one of each thing upgrade-checks.sql looks for onto the PostgreSQL 18 server, so the run
-- shows every check finding something. Nothing here belongs on a real server.
set client_min_messages = error;
set password_encryption = 'md5';
create role legacy_app login password 'fake-lab-only';
reset password_encryption;
alter role legacy_app set standard_conforming_strings = off;
alter system set io_workers = 4;
select pg_reload_conf();
create database mule_db encoding 'MULE_INTERNAL' locale 'C' template template0;
create role "two
lines";
create extension btree_gist;
create extension pg_trgm;
create table device(id int primary key, addr inet not null, label text not null, notes tsvector);
create index device_addr on device using gist (addr gist_inet_ops);
create index device_label_trgm on device using gin (label gin_trgm_ops);
create index device_notes_fts on device using gin (notes);
