(()=>{const G=window.G,SN=window.SN,P=window.PARTS,IM=window.IM;
P.push(G.h2('Changed defaults'));
P.push(G.p('A major version that changes defaults changes behaviour for everybody who never set them. These are the settings as the two servers reported them, untouched:'));
P.push(G.table(['Setting','18.7','19.0'],[
['<code>jit</code>','on','off'],
['<code>default_toast_compression</code>','pglz','lz4'],
['<code>max_locks_per_transaction</code>','64','128'],
['<code>io_workers</code>','3','removed'],
['<code>io_min_workers</code> / <code>io_max_workers</code>','not there','2 / 8'],
['<code>effective_wal_level</code>','not there','replica'],
['<code>max_repack_replication_slots</code>','not there','5'],
['<code>autovacuum_max_parallel_workers</code>','not there','0'],
['<code>password_expiration_warning_threshold</code>','not there','604800 (seven days)']]));
P.push(G.ul([
'<strong>JIT is off.</strong> The release notes say the cost model that decided when to compile was unreliable. For transaction processing this removes a known source of sudden slow queries. A warehouse that runs large analytical queries and benefited from JIT must now turn it on, and should measure before and after.',
'<strong>TOAST compression is lz4.</strong> It applies to values written after the change; existing values stay as they are. Measured below.',
'<strong>Lock table size.</strong> The default doubles, and the release notes say the allocation changed so that a setting must be doubled to keep the capacity it had. If you raised <code>max_locks_per_transaction</code> for a schema with many partitions, carry over twice your number, not your number.',
'<strong>I/O workers.</strong> <code>io_workers</code> is gone and the pool now sizes itself between <code>io_min_workers</code> and <code>io_max_workers</code>. A configuration file that still sets <code>io_workers</code> needs editing before the first start.',
'<strong>Parallel autovacuum</strong> exists and is off: <code>autovacuum_max_parallel_workers</code> is 0.']));
P.push(G.p('For the compression change I stored 20,000 documents of about 17 kB of repetitive JSON-like text, once with each method, on 19:'));
P.push(G.table(['Compression','Insert','Read every document','Size on disk'],[
['pglz','3,451 ms','310 ms','31 MB for 297 MB of text'],
['lz4','1,886 ms','299 ms','39 MB for 297 MB of text']]));
P.push(G.p('lz4 nearly halved the insert time, read at the same speed, and used a quarter more disk. For most systems that is the right trade and the reason for the new default. Where storage is the cost that matters, for example a large archive of documents that are written once, set <code>pglz</code> on those columns and keep it by choice. The text here compresses unusually well; measure with your own documents.'));

P.push(G.h2('Upgrade checks'));
P.push(G.p('The release notes list 22 incompatibilities. Most are narrow. The ones below can stop an upgrade or change behaviour silently, and each can be found on the old server with a query. The sample has a script, <code>sql/upgrade-checks.sql</code>, and this is its first half:'));
P.push(G.code('sql',SN('sql/upgrade-checks.sql','\\echo 1. Roles that still have an MD5 password','\\echo 4. Settings whose default changes')));
P.push(G.p('To show that each check finds what it looks for, the run first plants one of everything on the 18 server, then runs the script. All eight checks reported their planted item. What they cover:'));
P.push(G.table(['Check','What 19 does'],[
['Roles with an MD5 password','Warns after every successful login. MD5 was deprecated in 18. Reset those passwords under <code>scram-sha-256</code> before the upgrade.'],
['<code>pg_hba.conf</code> lines with <code>radius</code>','RADIUS authentication is removed. A server with such a line needs another method first.'],
['<code>io_workers</code>, <code>standard_conforming_strings</code>, <code>escape_string_warning</code> set anywhere','The first and third are removed. <code>standard_conforming_strings</code> is forced on, and a dump made by an older <code>pg_dump</code> with it off will not load correctly.'],
['Defaults for <code>jit</code>, <code>default_toast_compression</code>, <code>max_locks_per_transaction</code>','Change as in the table above, wherever the source is <code>default</code>.'],
['Databases in <code>MULE_INTERNAL</code>','The encoding is removed. Dump and restore in another encoding.'],
['Role, database or tablespace names with a line break','No longer allowed, and <code>pg_upgrade</code> refuses the cluster.'],
['<code>btree_gist</code> indexes on <code>inet</code> or <code>cidr</code>','<code>pg_upgrade</code> refuses the cluster. The release notes call those operator classes broken: they can leave out rows that should be returned. Rebuild the indexes without them.'],
['Indexes on full text search or <code>pg_trgm</code>','Reindex after <code>pg_upgrade</code>, and recompute stored <code>tsvector</code> values, when the database uses the ICU or builtin locale provider.']]));
P.push(G.p('Three more from the notes that no query finds. <code>json_array()</code> over a subquery with no rows now returns <code>[]</code>, where 18 returned NULL; the lab confirmed both, and any code that tests the result for NULL changes behaviour. In <code>pg_stat_subscription_stats</code> the column <code>sync_error_count</code> is now <code>sync_table_error_count</code>, and several buffer wait events were renamed, so check dashboards and alert rules. And a parallel <code>VACUUM</code> with cost-based delay now shares one budget between its workers, so it may run slower than before.'));
P.push(IM(2,'Upgrade checklist for PostgreSQL 19: defaults that change (jit, TOAST compression, lock table size, I/O workers) and things that are removed or refused (RADIUS, MULE_INTERNAL, standard_conforming_strings off, btree_gist indexes on inet and cidr, names with line breaks, MD5 warning)','What changes without being asked, and what stops an upgrade.'));

P.push(G.h2('Smaller SQL additions'));
P.push(G.p('Four additions that remove code people write by hand. Each is a syntax error or a missing function on 18.7; the lab ran each of them against both versions.'));
P.push(G.code('sql',SN('@r/03-tour.txt','-- 3. Carry the last known reading forward','drop schema tour cascade;')));
P.push(G.p('<code>IGNORE NULLS</code> in window functions is the most widely useful of the four. Carrying the last known value forward over gaps, in sensor readings or in any sparse time series, used to take a subquery with a running count to form groups. <code>COPY ... (FORMAT json)</code> writes a query result as JSON on the server, one object per line, or as one array with <code>FORCE_ARRAY</code>, which replaces a small export script.'));

P.push(G.h2('New views'));
P.push(G.p('Four things to add to a monitoring setup, all seen in the run:'));
P.push(G.ul([
'<strong><code>pg_stat_lock</code></strong> counts lock waits by lock type. After the repack experiment it held one line: <code>relation</code>, 4 waits, 20,187 ms. That is the queue behind <code>VACUUM FULL</code> and plain <code>REPACK</code>, now visible after the fact without sampling <code>pg_locks</code> at the right moment. The waits behind the concurrent form, all under a second, were not counted, so the view appears to record only waits above a threshold. I did not confirm which.',
'<strong><code>pg_stat_autovacuum_scores</code></strong> shows why autovacuum will or will not visit a table: a score for vacuum, for analyze and for wraparound, and the decisions <code>do_vacuum</code> and <code>do_analyze</code>. After the bulk inserts the lab\'s tables showed an analyze score in the tens of thousands and a vacuum score of zero. This replaces the arithmetic everybody does by hand with thresholds and scale factors.',
'<strong><code>pg_stat_recovery</code></strong> on a standby gives the replay position and pause state in one row.',
'<strong><code>EXPLAIN (ANALYZE, IO)</code></strong> adds read-ahead and asynchronous I/O figures to each scan, per worker.']));
P.push(G.code('text',SN('@r/results.txt','    Finalize Aggregate (actual rows=1.00 loops=1)','    Planning:')));

P.push(G.h2('Recommendation'));
P.push(G.p('Start testing now and do not put 19.0 under a system of record yet. The cautious practice with PostgreSQL is to take a new major version into production after its first or second minor release, and nothing here argues against it. <code>REPACK (CONCURRENTLY)</code> in particular is new machinery built on logical decoding that rewrites live tables; it did everything right in this lab, and one lab is not a track record.'));
P.push(G.p('What I would do in the meantime:'));
P.push(G.ul([
'<strong>Run the upgrade checks on every 18 cluster this month.</strong> The MD5, RADIUS and <code>btree_gist</code> items take time to fix and none of them needs 19 to start.',
'<strong>Put 19 in the CI matrix.</strong> The official image is there. The <code>json_array()</code> change and the JIT default are the kind of difference a test suite finds in an afternoon.',
'<strong>Replay the slow-query log.</strong> Look for <code>NOT IN</code> and for aggregates over joins. Those are the free gains, and they tell you how much the upgrade is worth.',
'<strong>Decide where each feature goes.</strong> <code>DO SELECT</code> and <code>IGNORE NULLS</code> are application changes that can only ship once every environment is on 19. <code>WAIT FOR LSN</code> needs a place to carry the position between requests, which is a design task to start now.',
'<strong>Plan the first concurrent repack on a table you can lose.</strong> Check the primary key, the free disk and the long-running readers first.']));
P.push(G.p('If your PostgreSQL is a managed service, the provider sets the date. Each service adds a new major version on its own schedule, and extensions follow at their own pace. I compared two such services last week in <a href="https://www.dataa.dev/2026/11/19/azure-horizondb-or-postgresql-flexible-server/">Azure HorizonDB or Azure Database for PostgreSQL Flexible Server</a>; neither ran 19 at that point.'));
P.push(G.p('For healthcare and other regulated workloads, two of these changes deserve a line in the validation plan. The standby pattern with <code>WAIT FOR LSN</code> removes a class of "the record I just saved is missing" defects, which in a clinical system is a patient-safety matter and not a cosmetic one. And any table rewrite of clinical data, concurrent or not, should be followed by the same row-count and checksum reconciliation you would run after a migration.'));

P.push(G.callout('note','HOW THIS WAS CHECKED','Everything in this article marked as measured comes from <a href="https://github.com/nithinmohantk/blog-samples-working-repo/actions/runs/45189048112" target="_blank" rel="noopener">GitHub Actions run 45189048112</a> of 23 November 2026, on the official <code>postgres:19</code> (19.0) and <code>postgres:18</code> (18.7) images on one hosted runner; the output files are on the <code>ci-results-postgresql-19-first-look</code> branch of the sample repository. All eleven experiments, the SQL tour and the eight upgrade checks completed without error. Three earlier runs the same day were used for the ranges quoted. Timings are single-machine comparisons with a median of three where stated; the repack figures are one run each. Not done: <code>pg_upgrade</code> was not run, so the items it refuses are taken from the release notes and only the detection queries were tested; <code>REPACK (CONCURRENTLY)</code> was not tested on partitioned or unlogged tables, under a long-running snapshot, or with a failure in the middle; the <code>standby_write</code> and <code>standby_flush</code> modes of <code>WAIT FOR LSN</code>, the new logical replication options, SNI, parallel autovacuum and the I/O worker settings were not tested; no managed service was tested; nothing here is a benchmark of absolute performance.'));
P.push(window.GETCODE);
P.push(G.h2('References &amp; Further Reading'));
P.push(G.box([
G.ref('https://www.postgresql.org/about/news/postgresql-19-released-3449/','PostgreSQL 19 Released!','The announcement from the PostgreSQL Global Development Group, 19 November 2026'),
G.ref('https://www.postgresql.org/docs/19/release-19.html','PostgreSQL 19 release notes','The full list of changes and the 22 incompatibilities'),
G.ref('https://www.postgresql.org/docs/19/sql-repack.html','REPACK','Syntax, the CONCURRENTLY option and its restrictions'),
G.ref('https://www.postgresql.org/docs/19/pgplanadvice.html','pg_plan_advice','The advice language and the EXPLAIN option'),
G.ref('https://www.dataa.dev/2026/11/19/azure-horizondb-or-postgresql-flexible-server/','Azure HorizonDB or Azure Database for PostgreSQL Flexible Server','The managed PostgreSQL comparison referred to above'),
G.ref('https://github.com/nithinmohantk/blog-samples-working-repo/tree/main/postgresql-19-first-look','Sample code for this article','The lab, the SQL tour, the upgrade checks and the script that starts the three servers')]));
})();
