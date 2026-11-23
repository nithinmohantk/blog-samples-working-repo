-- What to look for on a server before it goes to PostgreSQL 19. Tested against 18.
-- Checks 1 to 6 cover the whole cluster. Run checks 7 and 8 in every database.
\pset footer off

\echo 1. Roles that still have an MD5 password: 19 warns after every such login
select rolname from pg_authid where rolpassword like 'md5%' order by 1;

\echo 2. pg_hba.conf lines that use RADIUS: removed in 19
select line_number, type, database, user_name, address
from pg_hba_file_rules where auth_method = 'radius';

\echo 3. Settings that 19 removes or forces, set in a file or on the command line
select name, setting, source from pg_settings
where name in ('io_workers', 'standard_conforming_strings', 'escape_string_warning')
  and source <> 'default';

\echo 3b. The same settings, attached to a role or a database
select coalesce(r.rolname, '(every role)') as role, coalesce(d.datname, '(every database)') as database, c.setting
from pg_db_role_setting s
left join pg_roles r on r.oid = s.setrole
left join pg_database d on d.oid = s.setdatabase
cross join lateral unnest(s.setconfig) as c(setting)
where c.setting ~ '^(io_workers|standard_conforming_strings|escape_string_warning)=';

\echo 4. Settings whose default changes: where the source is default, the value will change under you
select name, setting, source from pg_settings
where name in ('jit', 'default_toast_compression', 'max_locks_per_transaction') order by 1;

\echo 5. Databases in the MULE_INTERNAL encoding: removed, dump and restore with another encoding
select datname from pg_database where pg_encoding_to_char(encoding) = 'MULE_INTERNAL';

\echo 6. Role, database and tablespace names with a line break in them: pg_upgrade refuses
select 'role' as kind, rolname as name from pg_roles where rolname ~ '[\n\r]'
union all select 'database', datname from pg_database where datname ~ '[\n\r]'
union all select 'tablespace', spcname from pg_tablespace where spcname ~ '[\n\r]';

\echo 7. btree_gist indexes on inet or cidr columns: pg_upgrade refuses, rebuild them with the core GiST opclass first
select i.indexrelid::regclass as index, i.indrelid::regclass as on_table, o.opcname
from pg_index i
join pg_opclass o on o.oid = any (i.indclass::oid[])
where o.opcname in ('gist_inet_ops', 'gist_cidr_ops');

\echo 8. Indexes built on full text search or pg_trgm: reindex after pg_upgrade unless the database uses the libc provider
select i.indexrelid::regclass as index, o.opcname
from pg_index i
join pg_opclass o on o.oid = any (i.indclass::oid[])
where o.opcname ~ '(tsvector_ops|trgm_ops)$';
select datname, case datlocprovider when 'c' then 'libc' when 'i' then 'icu' when 'b' then 'builtin' end as locale_provider
from pg_database where datname = current_database();
