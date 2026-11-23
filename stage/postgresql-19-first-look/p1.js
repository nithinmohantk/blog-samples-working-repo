(()=>{const G=window.G,SN=window.SN,P=window.PARTS,IM=window.IM;
const NEWS='<a href="https://www.postgresql.org/about/news/postgresql-19-released-3449/" target="_blank" rel="noopener">released on 19 November 2026</a>';
P.push(G.p('PostgreSQL 19 was '+NEWS+'. The announcement is long, and most of it reads the way release announcements do: a list of things that are now possible. I wanted to know which of them change a design decision, so I ran them. Three containers, PostgreSQL 19.0 as a primary with a streaming standby and PostgreSQL 18.7 beside them, and eleven experiments that put the same question to both versions.'));
P.push(G.p('Four things came out of it that I would act on. A table can now be rewritten to reclaim space while it stays in use: during a <code>REPACK (CONCURRENTLY)</code> of a 746 MB table, 414 writes finished, against 5 during <code>VACUUM FULL</code>. A <code>NOT IN</code> query that took 74 seconds on 18 took 29 milliseconds on 19, with no change to the SQL. A standby that was 200 ms behind returned stale data for 199 reads out of 200, and for none once the reader used the new <code>WAIT FOR LSN</code>. And logical decoding started on a server at <code>wal_level = replica</code> with no restart, which on 18 is an error.'));
P.push(G.p('There is also a list of things that will bite on upgrade day: three defaults change, one authentication method is gone, and <code>pg_upgrade</code> refuses some clusters outright. That list is near the end, with a script that finds each item on a running 18 server.'));
P.push(IM(1,'Six measured results from PostgreSQL 19.0 against 18.7: writes finished during a table rewrite, a NOT IN query, a bulk insert with a foreign key, WAL written by get-or-create, stale reads on a standby, and logical decoding without a restart','Six results from the run, PostgreSQL 19.0 beside 18.7 on the same machine.'));

P.push(G.h2('The test bench'));
P.push(G.p('Everything runs from one script on a GitHub Actions runner. It starts the official <code>postgres:19</code> and <code>postgres:18</code> images, copies the 19 primary with <code>pg_basebackup</code> to make a standby, and then a Python program runs the experiments and writes what it saw to a text file. All data is generated. The timings compare two things on the same machine minutes apart; they say nothing about your hardware.'));
P.push(G.mer(G.MF+`
flowchart TD
    L["Lab script:<br>11 experiments, generated data"] --> P["PostgreSQL 19.0<br>primary"]
    P --> S["PostgreSQL 19.0 standby:<br>streaming, replication slot"]
    L --> S
    L --> O["PostgreSQL 18.7:<br>the same statements, for comparison"]
    L --> R["results.txt:<br>what each statement answered"]
    style L fill:#FFF3E0,stroke:#FF9900,stroke-width:2px,color:#232F3E
    style P fill:#EBF8FF,stroke:#0073BB,stroke-width:2px,color:#004C74
    style S fill:#EBF8FF,stroke:#0073BB,stroke-width:2px,color:#004C74
    style O fill:#F3E8FF,stroke:#7C3AED,stroke-width:2px,color:#4C1D95
    style R fill:#F0FFF4,stroke:#1D8102,stroke-width:2px,color:#145202`));
P.push(G.p('One lesson arrived before the first experiment. My first standby had no replication slot. The experiments generate several gigabytes of WAL, the standby fell behind, the primary recycled a segment the standby still needed, and the standby stopped for good with <code>requested WAL segment has already been removed</code>. Creating the standby with a slot (<code>pg_basebackup -C -S standby1</code>) fixed it. Nothing about that is new in 19, and it is still the most common way to lose a replica.'));

P.push(G.h2('REPACK'));
P.push(G.p('<code>VACUUM FULL</code> and <code>CLUSTER</code> both rewrite a table, and both hold an <code>ACCESS EXCLUSIVE</code> lock for the whole rewrite, so nothing can read or write the table until they finish. That lock is why most teams never run either on a busy table and reach for an extension such as pg_repack or pg_squeeze. PostgreSQL 19 puts one command, <code>REPACK</code>, in place of both, and gives it a <code>CONCURRENTLY</code> option. This is the tour file from the sample, statements and answers together:'));
P.push(G.code('sql',SN('@r/03-tour.txt',"select pg_size_pretty(pg_total_relation_size('invoice')) as size_before;",'-- 2. Get or create')));
P.push(G.p('To see what "concurrently" is worth, the lab builds a table of 2.4 million rows, deletes every second row and runs a plain <code>VACUUM</code>, which leaves 746 MB holding 373 MB of data. Then one session updates a row and another reads a row about every 2 ms, while a third runs the rewrite.'));
P.push(G.table(['Statement','Took','Writes finished during it','Slowest write','Reads finished during it','Slowest read'],[
['<code>VACUUM FULL</code>','3.63 s','5','3,641 ms','21','3,633 ms'],
['<code>REPACK</code>','6.69 s','10','6,386 ms','64','6,579 ms'],
['<code>REPACK (CONCURRENTLY)</code>','6.60 s','414','898 ms','1,839','505 ms']]));
P.push(G.p('All three took the table from 746 MB to 373 MB, and in all three every update the writer had been told was committed was in the table afterwards. The difference is the middle columns. Under <code>VACUUM FULL</code> and plain <code>REPACK</code> the slowest write and the slowest read are as long as the statement: the sessions were queued behind the lock. Under <code>REPACK (CONCURRENTLY)</code> they kept working, with one pause of under a second that I take to be the moment the new files are swapped in under a short exclusive lock.'));
P.push(G.p('Two cautions about that table. The pause was 438, 458 and 898 ms in three runs, so read it as "a fraction of a second on a table this size" and plan for longer on a larger one. And do not read the "Took" column as a ranking: in an earlier run <code>VACUUM FULL</code> took 12.4 s and plain <code>REPACK</code> 6.1 s, the opposite order. On a shared runner I could not separate the two. Plain <code>REPACK</code> is a new name for what you already had, and the reason to care is the option.'));
P.push(G.p('While the concurrent rewrite ran, the lab watched two things. <code>effective_wal_level</code> went from <code>replica</code> to <code>logical</code> and back, and one logical replication slot existed and then did not. The concurrent rewrite is built on logical decoding: it copies the table, then replays the changes made meanwhile. That explains the conditions the documentation sets, two of which the lab hit:'));
P.push(G.ul([
'The table needs a primary key or an index set as its replica identity. Without one: <code>ERROR: cannot execute REPACK (CONCURRENTLY) on relation "no_key"</code>.',
'It cannot run inside a transaction block: <code>ERROR: REPACK (CONCURRENTLY) cannot run inside a transaction block</code>. A migration tool that wraps every step in a transaction needs an exception for it.',
'It needs free disk for a second copy of the table and its indexes.',
'It uses a replication slot from its own pool, <code>max_repack_replication_slots</code>, 5 by default.',
'The documentation lists partitioned and unlogged tables as not supported, and says the rewrite is not MVCC-safe: a transaction with a snapshot older than the rewrite can see the table as empty. I did not test those three.']));
P.push(G.callout('warning','LONG TRANSACTIONS','The MVCC note matters for reporting jobs and for <code>pg_dump</code>, which hold one snapshot for a long time. Schedule a concurrent repack so that it does not start while such a job is running against the same table, the same rule that applies to <code>TRUNCATE</code> and to table-rewriting forms of <code>ALTER TABLE</code>.'));

P.push(G.h2('Get or create in one statement'));
P.push(G.p('"Give me the id for this email, creating the row if there is none" is in almost every application, and until now PostgreSQL had no clean way to write it. <code>ON CONFLICT DO NOTHING RETURNING id</code> returns no row when the row already exists, so it needs a second query. The usual workaround, <code>DO UPDATE SET name = EXCLUDED.name</code>, returns the row by rewriting it. PostgreSQL 19 adds <code>DO SELECT</code>:'));
P.push(G.code('sql',SN('@r/03-tour.txt',"insert into customer(email, name) values ('ada@example.test', 'Ada')",'-- Lock the row that was found')));
P.push(G.p('The second statement wrote nothing and returned the existing row with its original name. The <code>old_id</code> column answers a question the workaround never could: was the row created or found? <code>RETURNING old</code> arrived in 18; with <code>DO SELECT</code> it is null for a row that was inserted and filled for one that was found.'));
P.push(G.p('The cost of the workaround is easy to measure. One existing row, then the same statement 5,000 times:'));
P.push(G.table(['On conflict','Rows returned','WAL written','Time on 19'],[
['<code>DO NOTHING RETURNING id</code>','0','22 kB','1,078 ms'],
['<code>DO UPDATE SET name = EXCLUDED.name RETURNING id</code>','5,000','850 kB','2,189 ms'],
['<code>DO SELECT RETURNING id</code>','5,000','22 kB','1,080 ms']]));
P.push(G.p('The no-op update writes a new row version and its WAL every time, 850 kB here for one unchanged row, and every one of those versions is work for vacuum and for every replica. <code>DO SELECT</code> writes what <code>DO NOTHING</code> writes and returns the row. On 18 the statement is a syntax error.'));
P.push(G.p('Three details from the run:'));
P.push(G.ul([
'<strong>Concurrency.</strong> Sixteen sessions ran the statement for the same new email at the same instant. One row was created and all sixteen got its id.',
'<strong>Locking.</strong> <code>DO SELECT FOR UPDATE</code> locks the row that was found, for a read followed by a write in the same transaction. A <code>WHERE</code> clause after it filters the found row, and when the filter does not match, no row comes back, so the caller must handle an empty result.',
'<strong>Identity values.</strong> All three forms used 5,001 identity values for 5,001 calls. The default is evaluated before the conflict is found. A get-or-create on a hot path still burns through a sequence, so use <code>bigint</code>.']));
})();
