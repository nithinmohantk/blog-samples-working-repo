(()=>{const G=window.G,SN=window.SN,P=window.PARTS,IM=window.IM;
P.push(G.h2('Read-your-writes on a standby'));
P.push(G.p('Sending reads to a standby has one well-known trap. A user saves a form, the write goes to the primary, the next page reads from a standby that has not replayed it yet, and the change appears to be lost. Teams work around it with sticky sessions, with a short "read from the primary after a write" window, or by polling the replay position. PostgreSQL 19 adds a statement for it: <code>WAIT FOR LSN</code>, run on the standby, returns when the standby has replayed up to a given position.'));
P.push(G.mer(G.MS+`
sequenceDiagram
    participant A as Application
    participant P as Primary
    participant S as Standby
    A->>P: UPDATE, commit
    A->>P: SELECT pg_current_wal_flush_lsn()
    P-->>A: 2/6692CEC8
    A->>S: WAIT FOR LSN '2/6692CEC8' WITH (TIMEOUT '5s')
    Note over S: Returns when replay reaches that position
    S-->>A: success
    A->>S: SELECT the row
    S-->>A: The value just written`));
P.push(G.p('This is the loop from the lab. It writes on the primary, takes the position, optionally waits on the standby, reads, and counts the reads that came back stale:'));
P.push(G.code('python',SN('lab/run.py','        def trial(label: str, wait: bool) -> None:','        trial("no added delay, read at once"')));
P.push(G.table(['Standby','Read at once','<code>WAIT FOR LSN</code> first','Wait, median'],[
['Keeping up, same machine','1 of 200 stale','0 of 200 stale','0.2 ms'],
['Applying 200 ms late','199 of 200 stale','0 of 200 stale','200.6 ms']]));
P.push(G.p('With both servers on one machine the standby is nearly always in time, and one read in 200 still missed. That is the worst kind of bug: rare enough to pass every test. With 200 ms of lag, set here through <code>recovery_min_apply_delay</code>, nearly every read is stale without the wait and none is with it, and the wait is exactly the lag.'));
P.push(G.p('The behaviour at the edges is what decides how to use it:'));
P.push(G.ul([
'When the position does not arrive in time, the statement raises an error: <code>timed out while waiting for target LSN FFFFFFFF/00000000 to be replayed</code>. With <code>NO_THROW</code> it returns the text <code>timeout</code> and the application decides, which is the form to use in a request path.',
'On success it returns <code>success</code>.',
'The default mode waits for replay and only works during recovery. On a primary it fails with <code>recovery is not in progress</code>, so the code must know which kind of server it is talking to. The mode <code>primary_flush</code> worked on the primary.',
'The syntax also has <code>standby_write</code> and <code>standby_flush</code> modes. I did not test them.']));
P.push(G.p('The design consequence: the position has to travel with the user. Return it from the write path, keep it in the session or a cookie, and pass it to the next read. Always set a timeout, and decide what a timeout means for each read: fall back to the primary for the page that must be right, show slightly old data for the one that need not be. Without a timeout, a stalled standby turns into a pile of waiting requests.'));

P.push(G.h2('Logical decoding without a restart'));
P.push(G.p('Change data capture, logical replication and several upgrade methods need <code>wal_level = logical</code>, and changing <code>wal_level</code> needs a restart. On a production primary that restart is a change request, a maintenance window and a failover rehearsal, and it is often the longest step in a CDC project. Most servers run at <code>replica</code> because that is the default.'));
P.push(G.table(['Step','PostgreSQL 18.7','PostgreSQL 19.0'],[
['<code>wal_level</code> at the start','replica','replica'],
['Create a logical replication slot','<code>ERROR: logical decoding requires "wal_level" &gt;= "logical"</code>','Created'],
['With the slot in place','','<code>wal_level</code> replica, <code>effective_wal_level</code> logical'],
['Decode an insert','','<code>table public.decode_me: INSERT: id[integer]:1 v[text]:\'hello\'</code>'],
['After dropping the slot','','<code>effective_wal_level</code> back to replica']]));
P.push(G.p('On 19 the server raises its own WAL level when the first logical slot is created and lowers it when the last one goes. No setting changed and nothing restarted. The new read-only setting <code>effective_wal_level</code> reports what is in force, and it is the one monitoring should read from now on.'));
P.push(G.p('Two things follow. A CDC connector can be attached to a 19 server at <code>replica</code> without a window. And WAL volume can now rise because somebody created a slot, with no configuration change to explain it: logical decoding writes more WAL per change. Creating a slot needs the <code>REPLICATION</code> attribute, so review who holds it, and alert on logical slots that exist and are not being read, because an abandoned slot holds WAL until the disk fills. That risk is old; what is new is that it no longer takes a restart to get there.'));

P.push(G.h2('Logical replication additions'));
P.push(G.p('Three additions to publications and subscriptions remove chores that every logical replication setup has carried. I tried them with the publisher and the subscriber as two databases on one 19 server, which is enough to see what is published and what arrives.'));
P.push(G.table(['Step','Result'],[
['<code>CREATE PUBLICATION pub_all FOR ALL TABLES EXCEPT (TABLE skip_me), ALL SEQUENCES</code>','Accepted. <code>pg_publication_tables</code> lists <code>keep_me</code> only. On 18.7 both <code>EXCEPT</code> and <code>ALL SEQUENCES</code> are syntax errors.'],
['<code>CREATE SUBSCRIPTION sub_all SERVER publisher PUBLICATION pub_all</code>','Accepted. The connection comes from a <code>postgres_fdw</code> foreign server and its user mapping.'],
['Initial copy','<code>keep_me</code> 2 rows, <code>skip_me</code> 0 rows, sequence at 14, as on the publisher'],
['Publisher adds a row to each table and draws 50 sequence values','<code>keep_me</code> 3 rows, <code>skip_me</code> 0 rows, sequence still at 14 while the publisher is at 64'],
['<code>ALTER SUBSCRIPTION sub_all REFRESH SEQUENCES</code>','Sequence at 64']]));
P.push(G.p('<strong>Publishing all tables except some.</strong> Until now the choice was <code>FOR ALL TABLES</code>, which takes everything including staging and audit tables, or a list of tables that somebody has to extend every time a table is created. <code>EXCEPT</code> gives the third option: everything, new tables included, apart from the ones named.'));
P.push(G.p('<strong>A subscription that names a server.</strong> With <code>SERVER</code>, the host and the credentials live in one foreign server and one user mapping instead of in a connection string inside each subscription. Rotating the replication password becomes one <code>ALTER USER MAPPING</code>. The documentation requires a user mapping for the subscription owner and <code>USAGE</code> on the server.'));
P.push(G.p('<strong>Sequences.</strong> This is the one to read carefully, and the fourth row of the table is why. Sequence values are copied when the subscription is created and when you ask. They are not replicated as they change: after 50 more values on the publisher, the subscriber still held 14 until <code>REFRESH SEQUENCES</code> ran. What this replaces is the script that every logical-replication cutover has needed, the one that reads each sequence on the old server and calls <code>setval</code> on the new one. The cutover order is now: stop writes, wait for the tables to catch up, <code>ALTER SUBSCRIPTION ... REFRESH SEQUENCES</code>, check, switch. Miss the refresh and the first insert on the new primary collides with an existing key.'));
P.push(G.p('To check for drift, the documentation compares <code>page_lsn</code> from <code>pg_get_sequence_data()</code> on the publisher with <code>srsublsn</code> in <code>pg_subscription_rel</code> on the subscriber; in the run they differed after the 50 values, as expected. It also notes that a sequence writes WAL once per block of cached values, 32 by default, so drift inside one block does not show. And it says the publisher must run 19 or later, so this does not help the move from 18 to 19. It helps the one after.'));
P.push(G.p('<strong>Conflicts with a concurrent delete.</strong> The subscription option <code>retain_dead_tuples</code> lets a subscriber recognise an update that arrives for a row deleted locally, the <code>update_deleted</code> conflict, which matters when two nodes both accept writes. Turning it on created a physical replication slot named <code>pg_conflict_detection</code>, and the server warned: <code>commit timestamp and origin data required for detecting conflicts won\'t be retained</code>. The detection needs <code>track_commit_timestamp</code>, which was off. The option holds back dead rows on the subscriber, so it has a bloat cost, and <code>max_retention_duration</code> caps it. I enabled the option and did not provoke a conflict.'));

P.push(G.h2('Planner changes'));
P.push(G.p('Three changes in the planner need no change to the application. The first is the one I would look for in my own slow-query log.'));
P.push(G.p('<code>NOT IN (subquery)</code> has always been a trap in PostgreSQL. Because of how SQL treats NULL, the planner could not turn it into an anti-join, so it ran the subquery as a filter, and once the subquery result outgrew <code>work_mem</code> it rescanned the result for every outer row. The lab has 5,000 orders and 300,000 blocked customers, both columns <code>NOT NULL</code>, and asks for the orders whose customer is not in the blocked list.'));
P.push(G.table(['Version','Time','Plan'],[
['18.7','74,236 ms','<code>Seq Scan on orders</code>, filter <code>NOT (ANY (customer_id = (SubPlan 1).col1))</code>'],
['19.0','29 ms','<code>Hash Right Anti Join</code>'],
['19.0, after <code>DROP NOT NULL</code> on <code>orders.customer_id</code>','not timed','the subplan filter again']]));
P.push(G.p('The third row is the condition. The planner makes the conversion only when it can prove no NULLs are involved, and here that proof came from the <code>NOT NULL</code> constraints. Remove one and the old plan is back. So the advice does not change for new code, write <code>NOT EXISTS</code>, and the fix for old code after the upgrade is often a constraint that should have been there anyway. Queries written by ORMs and reporting tools are where this will show up.'));
P.push(G.p('The second change is aggregation before a join. Summing 2,000,000 fact rows by a column of a 1,000-row dimension table, 19 aggregates the facts by the join key first and joins 1,000 partial results instead of 2,000,000 rows:'));
P.push(G.code('text',SN('@r/results.txt','    Finalize GroupAggregate','19, 2,000,000 facts joined to 1,000 dimensions, enable_eager_aggregate = off')));
P.push(G.p('With <code>enable_eager_aggregate</code> on, the default, the median of three runs was 333 ms; with it off, 519 ms, with a single aggregate above the join. Parallel query was turned off for this comparison to keep the plans readable.'));
P.push(G.p('The third is foreign key checks. The announcement says bulk inserts into tables with foreign keys were nearly twice as fast in the project\'s testing. Inserting 1,000,000 rows that each point at one of 100,000 parents:'));
P.push(G.table(['Version','With the foreign key','Without it','Cost of the check'],[
['18.7','5,715 ms','733 ms','4,982 ms'],
['19.0','2,705 ms','720 ms','1,985 ms']]));
P.push(G.p('18 took 2.11 times as long as 19, and the ratio was between 1.96 and 2.11 in four runs. The check still costs about three times the insert itself, so dropping constraints for a bulk load remains a real trade, with a smaller prize than before.'));

P.push(G.h2('Plan advice'));
P.push(G.p('PostgreSQL has never had query hints in core. Version 19 ships two modules that come close, and they are worth understanding before somebody on the team finds them. <code>pg_plan_advice</code> describes a plan as a short text and accepts the same text back as an instruction. <code>EXPLAIN (PLAN_ADVICE)</code> prints the advice for the plan the planner chose:'));
P.push(G.code('text',SN('@r/results.txt',"the planner's own choice, with EXPLAIN (COSTS OFF, PLAN_ADVICE):","with pg_plan_advice.advice = 'JOIN_ORDER(d f)")));
P.push(G.p('Setting <code>pg_plan_advice.advice</code> to <code>MERGE_JOIN_PLAIN(d)</code> turned the hash join into a merge join over the two indexes, and <code>EXPLAIN</code> reported the advice as <code>matched</code>. A longer string fixed the join order, the join method and the index together. Advice that named an index that does not exist was reported as <code>matched, inapplicable, failed</code>, and the query ran with the planner\'s own plan. Bad advice did not break the query.'));
P.push(G.p('The second module, <code>pg_stash_advice</code>, attaches advice to a query id so the application does not change. The lab created a stash with <code>pg_create_advice_stash(\'lab\')</code>, stored advice for the query\'s id with <code>pg_set_stashed_advice</code>, and set <code>pg_stash_advice.stash_name</code>. The same query text then produced:'));
P.push(G.code('text',SN('@r/results.txt',"with pg_stash_advice.stash_name = 'lab', the same query, nothing else set:",'## 10.')));
P.push(G.p('That is a production tool: a plan regression at two in the morning can be pinned without a deployment. It is also a way to collect plans that nobody remembers pinning. Treat each stashed entry as a change with an owner and a review date, because advice outlives the data distribution that justified it. In the lab the module was loaded per session with <code>LOAD</code>; I did not test it through <code>shared_preload_libraries</code>, and I did not test how advice behaves across a major version upgrade.'));
})();
