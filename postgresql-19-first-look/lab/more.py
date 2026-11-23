"""PostgreSQL 19, second part: logical replication additions, autovacuum, and what the statistics views gained.

Usage: python lab/more.py <output dir>

Expects two servers, started by ci-more.sh:
  127.0.0.1:5419  PostgreSQL 19
  127.0.0.1:5418  PostgreSQL 18, for comparison

The publisher and the subscriber are two databases on the same PostgreSQL 19 server. That is enough to
see what is published and what arrives. It says nothing about replication between machines.
"""
from __future__ import annotations

import sys
import time

import psycopg

from run import PG18, PG19, attempt, experiment, lines, one, say

OUT = sys.argv[1]
PASSWORD = "lab-only"   # the throwaway password ci-more.sh gives the containers


def db(port: int, dbname: str, notes: list[str] | None = None) -> psycopg.Connection:
    conn = psycopg.connect(host="127.0.0.1", port=port, user="postgres", password=PASSWORD, dbname=dbname, autocommit=True)
    if notes is not None:
        conn.add_notice_handler(lambda d: notes.append(f"{d.severity}: {d.message_primary}"))
    return conn


def until(check, seconds: float = 30.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if check():
            return True
        time.sleep(0.25)
    return False


SCHEMA = """
    create table keep_me(id int primary key, v text);
    create table skip_me(id int primary key, v text);
    create sequence ticket_no start with 10 increment by 1;
"""


# ---------------------------------------------------------------------------------------------
@experiment("12. Logical replication: all tables except one, sequences, and a subscription that names a server")
def replication():
    with db(PG18, "postgres") as old:
        old.execute("create table if not exists skip_me(id int primary key)")
        say(f"on 18, FOR ALL TABLES EXCEPT (TABLE skip_me): {attempt(old, 'create publication p1 for all tables except (table skip_me)')}")
        say(f"on 18, FOR ALL SEQUENCES: {attempt(old, 'create publication p2 for all sequences')}")

    with db(PG19, "postgres") as admin:
        admin.execute("create database pub_db")
        admin.execute("create database sub_db")
    notes: list[str] = []
    with db(PG19, "pub_db") as pub, db(PG19, "sub_db", notes) as sub:
        pub.execute(SCHEMA)
        sub.execute(SCHEMA)
        pub.execute("insert into keep_me values (1, 'a'), (2, 'b'); insert into skip_me values (1, 'x')")
        pub.execute("select nextval('ticket_no') from generate_series(1, 5)")
        say(f"publisher before: keep_me {one(pub, 'select count(*) from keep_me')} rows, skip_me {one(pub, 'select count(*) from skip_me')} row, ticket_no last_value {one(pub, 'select last_value from ticket_no')}")

        both = attempt(pub, "create publication pub_all for all tables except (table skip_me), all sequences")
        say(f"CREATE PUBLICATION pub_all FOR ALL TABLES EXCEPT (TABLE skip_me), ALL SEQUENCES: {both}")
        say(f"what pub_all publishes, from pg_publication_tables: {[r[0] for r in pub.execute('select tablename from pg_publication_tables where pubname = %s order by 1', ['pub_all']).fetchall()]}")

        # Publisher and subscriber share a server, so the slot is made first: CREATE SUBSCRIPTION would
        # otherwise wait for its own transaction to end.
        pub.execute("select pg_create_logical_replication_slot('sub_all', 'pgoutput')")
        sub.execute("create extension postgres_fdw")
        sub.execute("create server publisher foreign data wrapper postgres_fdw options (host 'localhost', port '5432', dbname 'pub_db')")
        sub.execute(f"create user mapping for postgres server publisher options (user 'postgres', password '{PASSWORD}')")
        created = attempt(sub, "create subscription sub_all server publisher publication pub_all with (create_slot = false, slot_name = 'sub_all')")
        say(f"CREATE SUBSCRIPTION sub_all SERVER publisher PUBLICATION pub_all: {created}")

        arrived = until(lambda: one(sub, "select count(*) from keep_me") == 2 and one(sub, "select last_value from ticket_no") == 14)
        say(f"subscriber after the initial copy (arrived in time: {arrived}): keep_me {one(sub, 'select count(*) from keep_me')} rows, skip_me {one(sub, 'select count(*) from skip_me')} rows, ticket_no last_value {one(sub, 'select last_value from ticket_no')}")

        pub.execute("insert into keep_me values (3, 'c'); insert into skip_me values (2, 'y')")
        pub.execute("select nextval('ticket_no') from generate_series(1, 50)")
        until(lambda: one(sub, "select count(*) from keep_me") == 3)
        time.sleep(3)
        say(f"publisher moves on: one more row in each table, 50 more tickets, ticket_no last_value {one(pub, 'select last_value from ticket_no')}")
        say(f"subscriber a few seconds later: keep_me {one(sub, 'select count(*) from keep_me')} rows, skip_me {one(sub, 'select count(*) from skip_me')} rows, ticket_no last_value {one(sub, 'select last_value from ticket_no')}")
        say(f"drift check: publisher page_lsn {one(pub, "select page_lsn from pg_get_sequence_data('ticket_no')")}, subscriber srsublsn {one(sub, "select srsublsn from pg_subscription_rel where srrelid = 'ticket_no'::regclass")}")
        say(f"ALTER SUBSCRIPTION sub_all REFRESH SEQUENCES: {attempt(sub, 'alter subscription sub_all refresh sequences')}")
        refreshed = until(lambda: one(sub, "select last_value from ticket_no") == 64)
        say(f"subscriber after the refresh (arrived in time: {refreshed}): ticket_no last_value {one(sub, 'select last_value from ticket_no')}")

        notes.clear()
        say(f"ALTER SUBSCRIPTION sub_all DISABLE, then SET (retain_dead_tuples = true): {attempt(sub, 'alter subscription sub_all disable')}, {attempt(sub, 'alter subscription sub_all set (retain_dead_tuples = true)')}")
        say(f"what the server said: {notes}")
        say(f"track_commit_timestamp on this server: {one(sub, 'show track_commit_timestamp')}")
        slots = sub.execute("select slot_name, slot_type from pg_replication_slots order by 1").fetchall()
        say(f"replication slots now: {slots}")
        sub.execute("alter subscription sub_all set (retain_dead_tuples = false)")
        sub.execute("alter subscription sub_all set (slot_name = none)")
        sub.execute("drop subscription sub_all")
        pub.execute("select pg_drop_replication_slot('sub_all')")


# ---------------------------------------------------------------------------------------------
@experiment("13. A read that marks pages all-visible")
def all_visible():
    say("a table of 200,000 rows with autovacuum turned off for it, never vacuumed. Pages marked all-visible, from pg_visibility_map_summary.")
    say("version | after the insert | after one SELECT count(*) | after a second | after VACUUM")
    for port, name in ((PG18, "18"), (PG19, "19")):
        with db(port, "postgres") as conn:
            conn.execute("create extension if not exists pg_visibility")
            conn.execute("drop table if exists readings; create table readings(id int, v text) with (autovacuum_enabled = off)")
            conn.execute("insert into readings select g, md5(g::text) from generate_series(1, 200000) g")
            pages = one(conn, "select pg_relation_size('readings') / current_setting('block_size')::int")
            seen = [one(conn, "select all_visible from pg_visibility_map_summary('readings')")]
            for _ in range(2):
                time.sleep(1.0)
                conn.execute("select count(*) from readings").fetchone()
                seen.append(one(conn, "select all_visible from pg_visibility_map_summary('readings')"))
            conn.execute("vacuum readings")
            seen.append(one(conn, "select all_visible from pg_visibility_map_summary('readings')"))
            say(f"{name} | {seen[0]} | {seen[1]} | {seen[2]} | {seen[3]} of {pages} pages")


# ---------------------------------------------------------------------------------------------
@experiment("14. Autovacuum settings and what the statistics views gained")
def views():
    with db(PG18, "postgres") as old, db(PG19, "postgres") as new:
        for conn in (old, new):
            conn.execute("create table if not exists big_index_table(id int primary key)")
        say(f"ALTER TABLE ... SET (autovacuum_parallel_workers = 2) | 18: {attempt(old, 'alter table big_index_table set (autovacuum_parallel_workers = 2)')} | 19: {attempt(new, 'alter table big_index_table set (autovacuum_parallel_workers = 2)')}")
        say("columns that 19 has and 18 does not:")
        for view in ("pg_stat_wal", "pg_stat_subscription_stats", "pg_stat_all_tables", "pg_stat_database", "pg_stat_activity", "pg_stat_replication_slots"):
            columns = [{r[0] for r in c.execute("select attname from pg_attribute where attrelid = %s::regclass and attnum > 0 and not attisdropped", [view]).fetchall()} for c in (old, new)]
            say(f"    {view}: added {sorted(columns[1] - columns[0])}, gone {sorted(columns[0] - columns[1])}")
        views_new = {r[0] for r in new.execute("select viewname from pg_views where schemaname = 'pg_catalog'").fetchall()}
        views_old = {r[0] for r in old.execute("select viewname from pg_views where schemaname = 'pg_catalog'").fetchall()}
        say(f"system views in 19 that 18 does not have: {sorted(views_new - views_old)}")
        say(f"system views in 18 that 19 does not have: {sorted(views_old - views_new)}")
        settings_new = {r[0] for r in new.execute("select name from pg_settings").fetchall()}
        settings_old = {r[0] for r in old.execute("select name from pg_settings").fetchall()}
        say(f"settings in 19 that 18 does not have ({len(settings_new - settings_old)}): {sorted(settings_new - settings_old)}")
        say(f"settings in 18 that 19 does not have ({len(settings_old - settings_new)}): {sorted(settings_old - settings_new)}")


if __name__ == "__main__":
    lines.clear()
    say(f"PostgreSQL 19 lab, second part, {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}")
    for run in (replication, all_visible, views):
        run()
    with open(f"{OUT}/more-results.txt", "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
