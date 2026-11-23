"""PostgreSQL 19, tried rather than read about.

Usage: python lab/run.py <output dir>

Expects three servers, started by ci.sh:
  127.0.0.1:5419  PostgreSQL 19, primary
  127.0.0.1:5420  PostgreSQL 19, streaming standby of the primary
  127.0.0.1:5418  PostgreSQL 18, for comparison

Every experiment writes what it saw to results.txt. One that fails says so and the rest still run.
All data is generated here. Nothing is a benchmark of your hardware: the timings compare two things
on the same machine, minutes apart.
"""
from __future__ import annotations

import json
import random
import statistics
import sys
import threading
import time
import traceback

import psycopg

OUT = sys.argv[1]
PG19, STANDBY, PG18 = 5419, 5420, 5418
lines: list[str] = []


def connect(port: int, **kw) -> psycopg.Connection:
    return psycopg.connect(host="127.0.0.1", port=port, user="postgres", password="lab-only", dbname="postgres", autocommit=True, **kw)


def say(text: str = "") -> None:
    lines.append(text)
    print(text, flush=True)


def one(conn, sql: str, params=None):
    row = conn.execute(sql, params).fetchone()
    return row[0] if row else None


def attempt(conn, sql: str) -> str:
    """Runs a statement and returns its first value, or the first line of the error."""
    try:
        cur = conn.execute(sql)
        if cur.description is None:
            return cur.statusmessage or "ok"
        row = cur.fetchone()
        return "(no rows)" if row is None else str(row[0])
    except psycopg.Error as error:
        return "ERROR: " + str(error).splitlines()[0]


def plan(conn, sql: str, options: str = "COSTS OFF") -> list[str]:
    return [row[0] for row in conn.execute(f"EXPLAIN ({options}) {sql}").fetchall()]


def timed(conn, sql: str) -> float:
    started = time.perf_counter()
    conn.execute(sql)
    return (time.perf_counter() - started) * 1000


def experiment(title: str):
    def wrap(function):
        def run():
            say()
            say(f"## {title}")
            try:
                function()
            except Exception as error:  # the record of a failure is a result too
                say(f"FAILED: {type(error).__name__}: {str(error).splitlines()[0]}")
                traceback.print_exc()
        return run
    return wrap


# ---------------------------------------------------------------------------------------------
@experiment("1. Defaults that changed")
def defaults():
    names = ["jit", "default_toast_compression", "max_locks_per_transaction", "io_workers", "io_min_workers", "io_max_workers",
             "wal_level", "effective_wal_level", "max_repack_replication_slots", "autovacuum_max_parallel_workers",
             "md5_password_warnings", "password_expiration_warning_threshold", "enable_eager_aggregate"]
    with connect(PG18) as old, connect(PG19) as new:
        say(f"18: {one(old, 'select version()').split(' on ')[0]} | 19: {one(new, 'select version()').split(' on ')[0]}")
        say("setting | 18 | 19")
        for name in names:
            values = [one(c, "select setting from pg_settings where name = %s", [name]) or "(not there)" for c in (old, new)]
            say(f"{name} | {values[0]} | {values[1]}")
        say("statement | 18 | 19")
        for sql in ["select json_array(select 1 where false)::text", "select coalesce(json_array(select 1 where false)::text, 'NULL')"]:
            say(f"{sql} | {attempt(old, sql)} | {attempt(new, sql)}")


# ---------------------------------------------------------------------------------------------
@experiment("2. Logical decoding without a restart")
def logical_without_restart():
    for port, name in ((PG18, "18"), (PG19, "19")):
        with connect(port) as conn:
            before = attempt(conn, "show wal_level")
            created = attempt(conn, "select slot_name from pg_create_logical_replication_slot('lab_slot', 'test_decoding')")
            say(f"{name}: wal_level={before} | create a logical slot: {created}")
            if created.startswith("ERROR"):
                continue
            say(f"{name}: with the slot: wal_level={attempt(conn, 'show wal_level')}, effective_wal_level={attempt(conn, 'show effective_wal_level')}")
            conn.execute("create table if not exists decode_me(id int primary key, v text)")
            conn.execute("insert into decode_me values (1, 'hello') on conflict (id) do nothing")
            changes = [row[0] for row in conn.execute("select data from pg_logical_slot_get_changes('lab_slot', null, null)").fetchall()]
            say(f"{name}: decoded changes: {[c for c in changes if 'decode_me' in c][:1]}")
            conn.execute("select pg_drop_replication_slot('lab_slot')")
            observed = []
            for _ in range(20):
                observed.append(attempt(conn, "show effective_wal_level"))
                if observed[-1] != "logical":
                    break
                conn.execute("checkpoint")
                time.sleep(0.5)
            say(f"{name}: after dropping the slot: effective_wal_level={observed[-1]} (after {len(observed)} looks, with checkpoints between)")


# ---------------------------------------------------------------------------------------------
BLOAT_ROWS = 2_400_000
KEEP_EVERY = 2   # every second row survives the delete


def make_bloated(conn, table: str) -> None:
    conn.execute(f"drop table if exists {table}")
    conn.execute(f"create table {table}(id bigint primary key, grp int not null, payload text not null)")
    conn.execute(f"insert into {table} select g, 0, repeat(md5(g::text), 8) from generate_series(1, {BLOAT_ROWS}) g")
    conn.execute(f"delete from {table} where id % {KEEP_EVERY} <> 0")
    conn.execute(f"vacuum {table}")


def size_mb(conn, table: str) -> float:
    return one(conn, "select pg_total_relation_size(%s::regclass)", [table]) / 1048576


def under_load(table: str, maintenance_sql: str) -> dict:
    """Runs one maintenance statement while a writer and a reader keep using the table."""
    stop = threading.Event()
    writes: list[tuple[float, float]] = []   # (finished at, milliseconds)
    reads: list[tuple[float, float]] = []
    levels: set[str] = set()
    slots: set[int] = set()

    def writer():
        with connect(PG19) as conn:
            rng = random.Random(7)
            while not stop.is_set():
                started = time.perf_counter()
                conn.execute(f"update {table} set grp = grp + 1 where id = %s", [rng.randrange(1, BLOAT_ROWS // KEEP_EVERY) * KEEP_EVERY])
                writes.append((time.perf_counter(), (time.perf_counter() - started) * 1000))
                time.sleep(0.002)

    def reader():
        with connect(PG19) as conn:
            rng = random.Random(11)
            while not stop.is_set():
                started = time.perf_counter()
                conn.execute(f"select grp from {table} where id = %s", [rng.randrange(1, BLOAT_ROWS // KEEP_EVERY) * KEEP_EVERY]).fetchone()
                reads.append((time.perf_counter(), (time.perf_counter() - started) * 1000))
                time.sleep(0.002)

    def watcher():
        with connect(PG19) as conn:
            while not stop.is_set():
                levels.add(one(conn, "show effective_wal_level"))
                slots.add(one(conn, "select count(*) from pg_replication_slots where slot_type = 'logical'"))
                time.sleep(0.05)

    threads = [threading.Thread(target=f) for f in (writer, reader, watcher)]
    for thread in threads:
        thread.start()
    time.sleep(1.0)
    with connect(PG19) as conn:
        before = size_mb(conn, table)
        started = time.perf_counter()
        conn.execute(maintenance_sql)
        finished = time.perf_counter()
        after = size_mb(conn, table)
    time.sleep(1.0)
    stop.set()
    for thread in threads:
        thread.join()
    with connect(PG19) as conn:
        applied = one(conn, f"select sum(grp) from {table}")
        rows = one(conn, f"select count(*) from {table}")
    during = lambda samples: [ms for at, ms in samples if started <= at <= finished + 0.05]
    return {
        "seconds": finished - started, "before": before, "after": after,
        "writes_during": len(during(writes)), "worst_write": max(during(writes) or [0]),
        "reads_during": len(during(reads)), "worst_read": max(during(reads) or [0]),
        "writes_total": len(writes), "applied": applied, "rows": rows, "levels": sorted(levels), "slots": sorted(slots),
    }


@experiment("3. REPACK against VACUUM FULL, with a writer and a reader on the table")
def repack():
    say(f"table: {BLOAT_ROWS:,} rows of about 300 bytes, every second one deleted, then plain VACUUM. A writer updates one row and a reader reads one row about every 2 ms.")
    say("statement | took | size before -> after | writes finished during it | slowest write | reads finished during it | slowest read | updates applied = updates acknowledged")
    statements = [("VACUUM FULL bloat_a", "bloat_a"), ("REPACK bloat_b", "bloat_b"), ("REPACK (CONCURRENTLY) bloat_c", "bloat_c")]
    for sql, table in statements:
        with connect(PG19) as conn:
            make_bloated(conn, table)
        r = under_load(table, sql)
        say(f"{sql} | {r['seconds']:.2f} s | {r['before']:.0f} -> {r['after']:.0f} MB | {r['writes_during']} | {r['worst_write']:.0f} ms | {r['reads_during']} | {r['worst_read']:.0f} ms | {r['applied']} = {r['writes_total']}: {r['applied'] == r['writes_total']} ({r['rows']:,} rows)")
        if "CONCURRENTLY" in sql:
            say(f"while REPACK (CONCURRENTLY) ran: effective_wal_level seen as {r['levels']}, logical replication slots seen: {r['slots']}")
    with connect(PG19) as conn:
        conn.execute("create index bloat_c_grp on bloat_c(grp)")
        conn.execute("analyze bloat_c")
        before = one(conn, "select correlation from pg_stats where tablename = 'bloat_c' and attname = 'grp'")
        conn.execute("REPACK (ANALYZE) bloat_c USING INDEX bloat_c_grp")
        after = one(conn, "select correlation from pg_stats where tablename = 'bloat_c' and attname = 'grp'")
        say(f"REPACK (ANALYZE) bloat_c USING INDEX bloat_c_grp | physical order against grp, correlation {before:.2f} -> {after:.2f}")
        say(f"REPACK (CONCURRENTLY) inside a transaction block: {attempt_in_transaction('REPACK (CONCURRENTLY) bloat_c')}")
        conn.execute("create table no_key(a int)")
        say(f"REPACK (CONCURRENTLY) on a table with no primary key: {attempt(conn, 'REPACK (CONCURRENTLY) no_key')}")
        waits = conn.execute("select locktype, waits, round(wait_time::numeric), fastpath_exceeded from pg_stat_lock where waits > 0 or fastpath_exceeded > 0 order by waits desc").fetchall()
        say(f"pg_stat_lock afterwards (locktype, waits, wait_time ms, fastpath_exceeded): {waits}")


def attempt_in_transaction(sql: str) -> str:
    with psycopg.connect(host="127.0.0.1", port=PG19, user="postgres", password="lab-only", dbname="postgres") as conn:
        try:
            conn.execute("select 1")
            conn.execute(sql)
            return "ok"
        except psycopg.Error as error:
            return "ERROR: " + str(error).splitlines()[0]


# ---------------------------------------------------------------------------------------------
@experiment("4. Get or create: INSERT ... ON CONFLICT DO SELECT")
def get_or_create():
    setup = "drop table if exists customer; create table customer(id bigint generated always as identity primary key, email text not null unique, name text not null)"
    patterns = {
        "DO NOTHING RETURNING id": "insert into customer(email, name) values (%s, %s) on conflict (email) do nothing returning id",
        "DO UPDATE SET name = EXCLUDED.name RETURNING id": "insert into customer(email, name) values (%s, %s) on conflict (email) do update set name = excluded.name returning id",
        "DO SELECT RETURNING id": "insert into customer(email, name) values (%s, %s) on conflict (email) do select returning id",
    }
    calls = 5000
    say(f"one existing row, then the same INSERT {calls:,} times | 18 | 19: rows returned | WAL written | table size after | identity values used | time")
    for label, sql in patterns.items():
        cells = []
        for port in (PG18, PG19):
            with connect(port) as conn:
                conn.execute(setup)
                try:
                    conn.execute(sql, ["ada@example.test", "Ada"])
                    conn.execute("checkpoint")
                    lsn = one(conn, "select pg_current_wal_insert_lsn()")
                    returned = 0
                    started = time.perf_counter()
                    for _ in range(calls):
                        returned += conn.execute(sql, ["ada@example.test", "Ada"]).rowcount
                    elapsed = time.perf_counter() - started
                    wal = one(conn, "select pg_wal_lsn_diff(pg_current_wal_insert_lsn(), %s)", [lsn])
                    used = one(conn, "select last_value from customer_id_seq")
                    size = one(conn, "select pg_relation_size('customer')")
                    cells.append(f"{returned} rows, {int(wal) / 1024:.0f} kB WAL, {size // 1024} kB, {used} identity values, {elapsed * 1000:.0f} ms")
                except psycopg.Error as error:
                    cells.append("ERROR: " + str(error).splitlines()[0])
        say(f"{label} | {cells[0]} | {cells[1]}")

    with connect(PG19) as conn:
        conn.execute(setup)
    barrier = threading.Barrier(16)
    ids: list[int] = []

    def racer():
        with connect(PG19) as conn:
            barrier.wait()
            ids.append(one(conn, patterns["DO SELECT RETURNING id"], ["grace@example.test", "Grace"]))

    threads = [threading.Thread(target=racer) for _ in range(16)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    with connect(PG19) as conn:
        say(f"16 sessions get-or-create the same new email at once: ids returned {sorted(set(ids))}, rows in the table {one(conn, 'select count(*) from customer')}")
        locked = attempt(conn, "insert into customer(email, name) values ('grace@example.test', 'x') on conflict (email) do select for update where customer.name = 'Grace' returning name")
        say(f"DO SELECT FOR UPDATE WHERE customer.name = 'Grace' RETURNING name: {locked}")
        filtered = attempt(conn, "insert into customer(email, name) values ('grace@example.test', 'x') on conflict (email) do select where customer.name = 'nobody' returning name")
        say(f"DO SELECT WHERE customer.name = 'nobody' RETURNING name: {filtered}")
    for label in ("DO NOTHING RETURNING id", "DO SELECT RETURNING id"):
        with psycopg.connect(host="127.0.0.1", port=PG19, user="postgres", password="lab-only", dbname="postgres") as conn:
            conn.execute(patterns[label], ["grace@example.test", "Grace"])
            assigned = one(conn, "select pg_current_xact_id_if_assigned() is not null")
            say(f"after a conflicting {label}, the transaction has a transaction id: {assigned}")


# ---------------------------------------------------------------------------------------------
@experiment("5. Read your own write on a standby: WAIT FOR LSN")
def wait_for_lsn():
    rounds = 200
    with connect(PG19) as primary, connect(STANDBY) as standby:
        primary.execute("drop table if exists kv; create table kv(k int primary key, v int not null); insert into kv values (1, 0)")
        time.sleep(1.5)
        say(f"standby in recovery: {one(standby, 'select pg_is_in_recovery()')} | pg_stat_recovery: {standby.execute('select last_replayed_end_lsn, pause_state from pg_stat_recovery').fetchone()}")

        def trial(label: str, wait: bool) -> None:
            stale, waits = 0, []
            for i in range(1, rounds + 1):
                primary.execute("update kv set v = %s where k = 1", [i])
                lsn = one(primary, "select pg_current_wal_flush_lsn()")
                if wait:
                    started = time.perf_counter()
                    standby.execute(f"WAIT FOR LSN '{lsn}' WITH (MODE 'standby_replay', TIMEOUT '5s')")
                    waits.append((time.perf_counter() - started) * 1000)
                stale += one(standby, "select v from kv where k = 1") != i
            extra = f", wait median {statistics.median(waits):.1f} ms, worst {max(waits):.1f} ms" if waits else ""
            say(f"{label}: {stale} of {rounds} reads on the standby did not see the write just made{extra}")

        trial("no added delay, read at once", wait=False)
        trial("no added delay, WAIT FOR LSN first", wait=True)
        standby.execute("alter system set recovery_min_apply_delay = '200ms'")
        standby.execute("select pg_reload_conf()")
        time.sleep(1.0)
        trial("standby applies 200 ms late, read at once", wait=False)
        trial("standby applies 200 ms late, WAIT FOR LSN first", wait=True)
        standby.execute("alter system reset recovery_min_apply_delay")
        standby.execute("select pg_reload_conf()")

        far = "FFFFFFFF/0"
        say(f"an LSN that never arrives, TIMEOUT '300ms': {attempt(standby, f"WAIT FOR LSN '{far}' WITH (TIMEOUT '300ms')")}")
        say(f"the same with NO_THROW: returns {attempt(standby, f"WAIT FOR LSN '{far}' WITH (TIMEOUT '300ms', NO_THROW)")!r}")
        lsn = one(primary, "select pg_current_wal_flush_lsn()")
        say(f"a reached LSN: returns {attempt(standby, f"WAIT FOR LSN '{lsn}' WITH (TIMEOUT '5s')")!r}")
        say(f"MODE 'standby_replay' on the primary: {attempt(primary, f"WAIT FOR LSN '{lsn}' WITH (MODE 'standby_replay', TIMEOUT '1s')")}")
        say(f"MODE 'primary_flush' on the primary: {attempt(primary, f"WAIT FOR LSN '{lsn}' WITH (MODE 'primary_flush', TIMEOUT '1s')")}")
    with connect(PG18) as old:
        say(f"on 18: {attempt(old, "WAIT FOR LSN '0/1'")}")


# ---------------------------------------------------------------------------------------------
@experiment("6. Smaller SQL additions, with the answer from 18 beside each")
def small_sql():
    statements = [
        ("carry the last reading forward", "select string_agg(coalesce(filled::text, '-'), ' ' order by ts) from (select ts, last_value(reading) ignore nulls over (order by ts) as filled from (values (1, 20), (2, null), (3, null), (4, 23), (5, null)) t(ts, reading)) s"),
        ("random date in a range", "select pg_typeof(random(date '2026-01-01', date '2026-12-31'))::text"),
        ("jsonpath string methods", """select jsonb_path_query('{"name": "  Ada Lovelace  "}', '$.name.btrim().upper()')::text"""),
        ("jsonpath split_part", """select jsonb_path_query('"2026-11-19"', '$.split_part("-", 1)')::text"""),
    ]
    with connect(PG18) as old, connect(PG19) as new:
        say("what | 18 | 19")
        for label, sql in statements:
            say(f"{label} | {attempt(old, sql)} | {attempt(new, sql)}")
        new.execute("drop table if exists copy_me; create table copy_me(id int, email text, tags text[]); insert into copy_me values (1, 'ada@example.test', '{a,b}'), (2, 'grace@example.test', null)")
        for options in ("FORMAT json", "FORMAT json, FORCE_ARRAY"):
            with new.cursor().copy(f"COPY (select * from copy_me order by id) TO STDOUT ({options})") as copy:
                text = b"".join(bytes(chunk) for chunk in copy).decode()
            say(f"COPY ... TO STDOUT ({options}) on 19:")
            for row in text.rstrip("\n").split("\n"):
                say("    " + row)
        old.execute("drop table if exists copy_me; create table copy_me(id int)")
        say(f"COPY ... (FORMAT json) on 18: {attempt(old, 'COPY copy_me TO STDOUT (FORMAT json)')}")


# ---------------------------------------------------------------------------------------------
@experiment("7. Planner: NOT IN, and aggregating before a join")
def planner():
    setup = """
        drop table if exists orders, blocked;
        create table blocked(customer_id int primary key);
        create table orders(id int primary key, customer_id int not null);
        insert into blocked select g from generate_series(1, 300000) g;
        insert into orders select g, 300000 + g from generate_series(1, 5000) g;
        analyze blocked; analyze orders;
    """
    query = "select count(*) from orders where customer_id not in (select customer_id from blocked)"
    say("5,000 orders, 300,000 blocked customers, both columns NOT NULL, no order is blocked. work_mem at its default.")
    for port, name in ((PG18, "18"), (PG19, "19")):
        with connect(port) as conn:
            conn.execute(setup)
            conn.execute("set statement_timeout = '120s'")
            shape = [line.strip() for line in plan(conn, query) if "Join" in line or "SubPlan" in line or "Seq Scan on orders" in line or "Filter" in line]
            try:
                started = time.perf_counter()
                count = one(conn, query)
                took = f"{(time.perf_counter() - started) * 1000:.0f} ms, count {count}"
            except psycopg.Error as error:
                took = "stopped: " + str(error).splitlines()[0]
            say(f"{name}: {took} | plan: {' / '.join(shape)}")
    with connect(PG19) as conn:
        conn.execute("alter table orders alter column customer_id drop not null")
        shape = [line.strip() for line in plan(conn, query) if "Join" in line or "SubPlan" in line]
        say(f"19, after the NOT NULL is dropped from orders.customer_id: plan: {' / '.join(shape)}")

        conn.execute("""
            drop table if exists fact, dim;
            create table dim(id int primary key, region text not null);
            create table fact(id bigint primary key, dim_id int not null, amount numeric(10,2) not null);
            insert into dim select g, 'region-' || (g % 20) from generate_series(1, 1000) g;
            insert into fact select g, 1 + g % 1000, (g % 500) / 7.0 from generate_series(1, 2000000) g;
            analyze dim; analyze fact;
        """)
        aggregate = "select d.region, sum(f.amount) from fact f join dim d on d.id = f.dim_id group by d.region"
        for setting in ("on", "off"):
            conn.execute(f"set enable_eager_aggregate = {setting}")
            conn.execute("set max_parallel_workers_per_gather = 0")
            times = sorted(timed(conn, aggregate) for _ in range(3))
            say(f"19, 2,000,000 facts joined to 1,000 dimensions, enable_eager_aggregate = {setting}: median {times[1]:.0f} ms, plan:")
            for line in plan(conn, aggregate):
                say("    " + line)
        conn.execute("reset enable_eager_aggregate")


# ---------------------------------------------------------------------------------------------
@experiment("8. Bulk insert into a table with a foreign key")
def foreign_keys():
    rows = 1_000_000
    say(f"{rows:,} rows inserted in one statement, each pointing at one of 100,000 parents. Median of three, in ms.")
    say("version | with the foreign key | without it | cost of the check")
    results = {}
    for port, name in ((PG18, "18"), (PG19, "19")):
        with connect(port) as conn:
            conn.execute("drop table if exists child, child_plain, parent; create table parent(id int primary key); insert into parent select g from generate_series(1, 100000) g; analyze parent")
            conn.execute("create table child(id int, parent_id int not null references parent(id)); create table child_plain(id int, parent_id int not null)")
            medians = []
            for table in ("child", "child_plain"):
                times = []
                for _ in range(3):
                    conn.execute(f"truncate {table}")
                    times.append(timed(conn, f"insert into {table} select g, 1 + g % 100000 from generate_series(1, {rows}) g"))
                medians.append(sorted(times)[1])
            results[name] = medians
            say(f"{name} | {medians[0]:.0f} | {medians[1]:.0f} | {medians[0] - medians[1]:.0f}")
    say(f"with the foreign key, 18 took {results['18'][0] / results['19'][0]:.2f} times as long as 19")


# ---------------------------------------------------------------------------------------------
@experiment("9. Plan advice")
def plan_advice():
    query = "select * from join_fact f join join_dim d on f.dim_id = d.id"
    with connect(PG19) as conn:
        conn.execute("""
            drop table if exists join_fact, join_dim;
            create table join_dim(id int primary key, label text);
            create table join_fact(id int primary key, dim_id int not null);
            insert into join_dim select g, 'd' || g from generate_series(1, 1000) g;
            insert into join_fact select g, 1 + g % 1000 from generate_series(1, 100000) g;
            create index join_fact_dim on join_fact(dim_id);
            analyze join_dim; analyze join_fact;
        """)
        conn.execute("load 'pg_plan_advice'")
        say("the planner's own choice, with EXPLAIN (COSTS OFF, PLAN_ADVICE):")
        for line in plan(conn, query, "COSTS OFF, PLAN_ADVICE"):
            say("    " + line)
        for advice in ("MERGE_JOIN_PLAIN(d)", "JOIN_ORDER(d f) NESTED_LOOP_PLAIN(f) INDEX_SCAN(f join_fact_dim)", "INDEX_SCAN(f no_such_index)"):
            conn.execute("select set_config('pg_plan_advice.advice', %s, false)", [advice])
            say(f"with pg_plan_advice.advice = '{advice}':")
            for line in plan(conn, query):
                say("    " + line)
        conn.execute("reset pg_plan_advice.advice")

        say("pg_stash_advice: advice attached to a query id, applied with no change to the query or the session's advice setting")
        conn.execute("create extension if not exists pg_stash_advice")
        settings = conn.execute("select name, setting from pg_settings where name like 'pg_stash_advice.%' order by 1").fetchall()
        say(f"settings: {settings}")
        query_id = json.loads(json.dumps(conn.execute(f"EXPLAIN (VERBOSE, FORMAT JSON) {query}").fetchone()[0]))[0].get("Query Identifier")
        say(f"query id from EXPLAIN (VERBOSE): {'found' if query_id else 'none: compute_query_id is off'}")
        conn.execute("select pg_create_advice_stash('lab')")
        conn.execute("select pg_set_stashed_advice('lab', %s, 'MERGE_JOIN_PLAIN(d)')", [query_id])
        say(f"stashes: {conn.execute('select * from pg_get_advice_stashes()').fetchall()}")
        name = next((n for n, _ in settings if "stash" in n.split('.')[1]), None)
        if name:
            conn.execute("select set_config(%s, 'lab', false)", [name])
            say(f"with {name} = 'lab', the same query, nothing else set:")
            for line in plan(conn, query):
                say("    " + line)


# ---------------------------------------------------------------------------------------------
@experiment("10. TOAST compression: pglz, the old default, against lz4, the new one")
def toast():
    with connect(PG19) as conn:
        document = """(select string_agg(format('{"sku":"SKU-%s","qty":%s,"note":"standard delivery, leave with a neighbour"}', (i * g) % 5000, i % 7), ',') from generate_series(1, 200) i)"""
        say("20,000 rows, each a document of about 17 kB of JSON-like text, on 19. Median of three, in ms.")
        say("compression | insert | read every document | table size")
        for method in ("pglz", "lz4"):
            conn.execute(f"drop table if exists docs_{method}; create table docs_{method}(id int primary key, doc text compression {method})")
            inserts, reads = [], []
            for _ in range(3):
                conn.execute(f"truncate docs_{method}")
                inserts.append(timed(conn, f"insert into docs_{method} select g, {document} from generate_series(1, 20000) g"))
                reads.append(timed(conn, f"select sum(length(doc)) from docs_{method}"))
            size = size_mb(conn, f"docs_{method}")
            raw = one(conn, f"select sum(length(doc)) from docs_{method}") / 1048576
            say(f"{method} | {sorted(inserts)[1]:.0f} | {sorted(reads)[1]:.0f} | {size:.0f} MB for {raw:.0f} MB of text")


# ---------------------------------------------------------------------------------------------
@experiment("11. New things to look at")
def monitoring():
    with connect(PG19) as conn:
        rows = conn.execute("select relname, round(score::numeric, 2), round(vacuum_score::numeric, 2), round(analyze_score::numeric, 2), do_vacuum, do_analyze from pg_stat_autovacuum_scores where schemaname = 'public' order by score desc limit 4").fetchall()
        say("pg_stat_autovacuum_scores, top four (relname, score, vacuum_score, analyze_score, do_vacuum, do_analyze):")
        for row in rows:
            say(f"    {row}")
        say("EXPLAIN (ANALYZE, IO, COSTS OFF, TIMING OFF, SUMMARY OFF) select count(*) from fact:")
        for line in plan(conn, "select count(*) from fact", "ANALYZE, IO, COSTS OFF, TIMING OFF, SUMMARY OFF"):
            say("    " + line)
        say("EXPLAIN (ANALYZE, WAL, COSTS OFF, TIMING OFF, SUMMARY OFF) update kv set v = v + 1, just after a checkpoint:")
        conn.execute("checkpoint")
        for line in plan(conn, "update kv set v = v + 1", "ANALYZE, WAL, COSTS OFF, TIMING OFF, SUMMARY OFF"):
            say("    " + line)


if __name__ == "__main__":
    say(f"PostgreSQL 19 lab, {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}")
    for run in (defaults, logical_without_restart, repack, get_or_create, wait_for_lsn, small_sql, planner, foreign_keys, plan_advice, toast, monitoring):
        run()
    with open(f"{OUT}/results.txt", "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
