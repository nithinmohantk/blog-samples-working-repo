eval(localStorage.art_H); const G=window.G,p=G.p,h2=G.h2; const snip=window.snip;
const RUN='https://github.com/nithinmohantk/blog-samples-working-repo/actions/runs/43473706809';
const REPO='https://github.com/nithinmohantk/blog-samples-working-repo/tree/main/sqlserver2025-vector-json';
const parts=[
h2('Security, compliance and operations'),
G.table(['Concern','What applies'],[
['Preview features in production','<code>PREVIEW_FEATURES</code> is per database and off by default. Decide as policy whether any production database may turn it on, and audit <code>sys.database_scoped_configurations</code>. Behaviour behind the switch can change in any update'],
['Embeddings as personal data','A vector computed from text about a person is derived from personal data and falls under the same GDPR duties as the text. In one engine, deleting the row deletes the embedding, and the same access rules and audit cover both. With a second store, erasure and permission changes have to be propagated and proven'],
['Encryption','Encryption at rest and in transit cover both types. The documentation lists Always Encrypted as not supported for <code>vector</code> columns'],
['Ledger','The documentation states that ledger verification raises an error if the database contains a table with a <code>vector</code> column. Check this before adding vectors to a ledger database'],
['Row-level security and the vector index','Because filters apply after an approximate search, a security predicate can leave a caller with few or no results. Use exact search, or one index per security boundary'],
['Approximate results in regulated workflows','An approximate index misses some true neighbours by design. Do not put one in a path where a missed record is a safety or compliance failure. In healthcare, that includes any lookup a clinical decision depends on'],
['Drivers','Native types need Microsoft.Data.SqlClient 6.0 for <code>json</code> and 6.1 for <code>vector</code>. Older clients keep working with text'],
['Log and backup volume','A JSON index multiplied the log written by an update by ten in this test. Size log backups and replication for it'],
['Monitoring','Track recall yourself: keep a sample of queries, run them both exact and approximate after each index build, and alert on the difference'],
['Pipeline','Pin the image tag, generate the password per run, and run the schema and the critical queries against each cumulative update before it reaches production']]),
h2('Cost'),
p(`Neither type adds a service to pay for. The cost is capacity in the database you already run.`),
G.table(['Item','From the run','What it implies'],[
['Vector storage','1,645 bytes per row at 384 dimensions','About 1.6 GB per million rows. Four times the dimensions is four times the bytes'],
['Exact search','14 ms and 10,543 pages per query for 50,000 rows','CPU and buffer pool grow with rows per query. Filter first'],
['Vector index build','128 s for 50,000 rows','A scheduled job with its own window, repeated after every load'],
['JSON storage','528 bytes per document as <code>json</code>, 331 as UTF-8 text','Not a saving for small documents'],
['JSON index','13.4 MB for two paths over 25 MB of documents; ten times the log on update','Storage, log backup and replica traffic']]),
p(`Edition limits set the outer boundary. Express edition now allows 50 GB per database, which holds a useful number of vectors for a small product. Standard edition is limited to 32 cores and 256 GB of buffer pool. A free Standard Developer edition exists alongside the Enterprise one, so a team that deploys on Standard can develop and test against the same feature set. A second, dedicated store has its own bill; compare it with the extra capacity above, not with zero.`),
h2('Decision framework'),
G.mer(G.MF+`
flowchart TD
    A["Embeddings or documents next to<br/>relational data in SQL Server"] --> B{"Rows a query must rank,<br/>after filters?"}
    B -- "up to a few hundred thousand" --> E["vector column and exact search<br/>with VECTOR_DISTANCE"]
    B -- "millions" --> C{"Is the table written to<br/>while it is searched?"}
    C -- "no, rebuilt on a schedule" --> D{"May production turn on<br/>preview features?"}
    C -- "yes" --> X["A dedicated vector store,<br/>or wait for a later update"]
    D -- "yes" --> V["Read-only search copy<br/>with a vector index"]
    D -- "no" --> X
    style E fill:#F0FFF4,stroke:#1D8102,stroke-width:2px,color:#145202
    style V fill:#FFF3E0,stroke:#FF9900,stroke-width:2px,color:#232F3E
    style X fill:#F3E8FF,stroke:#7C3AED,stroke-width:2px,color:#4C1D95`),
G.table(['Situation','Choose','Reason'],[
['New JSON column','<code>json</code>','Validation and faster reads and updates than <code>nvarchar(max)</code>'],
['Existing JSON in <code>nvarchar(max)</code>','Change the type after finding invalid rows','One statement, one way, and it normalises the text'],
['Payloads that must be returned byte for byte','A text column, possibly beside a <code>json</code> one','The native type removes white space and duplicate keys'],
['A known property queried by equality or range','Computed column and B-tree index','Chosen by the optimiser, narrow, cheap to maintain'],
['Containment over many or unknown paths','JSON index, queried with <code>JSON_CONTAINS</code>','What it was used for in the run. Budget for the write cost'],
['Semantic search over thousands to a few hundred thousand rows','<code>vector</code> and exact search','Correct, filterable, writable, nothing in preview'],
['Semantic search over millions of rows that change all day','A dedicated store today','The vector index in this build blocks writes and filters late']]),
h2('Key takeaways'),
G.ul([
`The <code>vector</code> and <code>json</code> types, their functions and the JSON index worked with the preview switch off in build 17.0.4040.1. The vector index, <code>VECTOR_SEARCH</code> and float16 vectors needed it on.`,
`Exact vector search ranked 50,000 rows of 384 dimensions in 14 ms and matched a brute-force calculation for every query. For data that filters down to that scale it needs no index and no second store.`,
`The vector index answered in 4 ms with 96% mean recall, took 128 seconds to build, made its table read-only, and applied filters after the search, returning one row on average when ten were asked for under a one-in-eight filter.`,
`<code>json</code> was a fifth smaller than <code>nvarchar(max)</code> and larger than UTF-8 text. It updates a same-length value in place, and it removes white space and duplicate keys, so it is not an archive of the original bytes.`,
`A JSON index was used for <code>JSON_CONTAINS</code> and not chosen for <code>JSON_VALUE</code> equality, and it made an update of an indexed property twenty-six times slower. For a known property, a computed column with a B-tree index did the same lookup at a fraction of the upkeep.`]),
p(`If you are running the vector index on a later update, I would like to know whether the table is still read-only and whether filters still apply after the search. Leave a comment.`),
G.callout('note','HOW THIS WAS CHECKED',`Everything shown ran in GitHub Actions on a hosted Linux runner with four vCPUs and 16 GB of memory, against <code>mcr.microsoft.com/mssql/server:2025-CU4-GDR1-ubuntu-22.04</code>, build 17.0.4040.1, with the container limited to 6 GB, from a .NET 10 program using Microsoft.Data.SqlClient 6.1.1. Eight checks passed, among them: three known distances, the ten nearest neighbours and their distances against a brute-force calculation in C# for 50 queries, a vector read back bit for bit through the driver, and the same count and total from six ways of querying the JSON documents. The other results are the server's own answers, recorded as returned. Timings are medians of 50 vector queries and 15 runs of each JSON query, taken once; the updates were run once each. Not run: vectors from a real embedding model, more than 50,000 rows, float16 beyond creating a table, Standard or Express edition, Windows, availability groups or replication, concurrent load, and any later cumulative update. Recall and timing depend on the data, and synthetic clusters are not a substitute for your own. <a href="${RUN}" target="_blank" rel="noopener">The run is here</a>.`),
G.callout('tip','GET THE CODE',`The T-SQL batches, the lab program, the image-tag picker and the pipeline script are in <a href="${REPO}" target="_blank" rel="noopener">sqlserver2025-vector-json</a> in the samples repository. <code>./ci.sh out</code> starts the container and runs everything with Docker and Python 3; set <code>LAB_SQL_CONNECTION</code> to run the program against a server of your own.`).replace('class="callout callout-tip"','class="callout callout-tip sample-code-link"'),
h2('Glossary'),
G.box([
G.term('Embedding','A list of numbers that represents a piece of text or an image so that similar items have nearby values.'),
G.term('Vector','Here, the SQL Server type that stores such a list with a fixed number of dimensions.'),
G.term('Cosine distance','One minus the cosine of the angle between two vectors: 0 for the same direction, 1 for perpendicular.'),
G.term('Exact nearest-neighbour search','Measuring the distance to every candidate row and keeping the closest. Always correct, linear in the number of rows.'),
G.term('Approximate nearest-neighbour search','Using an index to find most of the closest rows without measuring them all.'),
G.term('Recall','The share of the true nearest rows that an approximate search returned.'),
G.term('DiskANN','The graph-based approximate index algorithm, from Microsoft Research, that the vector index uses.'),
G.term('PREVIEW_FEATURES','A database-scoped setting in SQL Server 2025 that makes unfinished features available in that database.'),
G.term('Computed column','A column whose value is an expression over other columns, which can be indexed like any other.'),
G.term('JSON index','An index over one or more paths inside a json column.'),
G.term('Transaction log','The record of every change, written before the change is durable. Its volume drives backup size and replication traffic.'),
G.term('Cumulative update','A scheduled SQL Server update that contains all fixes since release. A GDR is a security-only update on top of one.')]),
h2('References &amp; Further Reading'),
G.box([
G.ref('https://learn.microsoft.com/sql/sql-server/what-s-new-in-sql-server-2025','What\'s new in SQL Server 2025','Microsoft: the feature list, preview features and edition changes'),
G.ref('https://learn.microsoft.com/sql/t-sql/data-types/vector-data-type','Vector data type','Microsoft: dimensions, conversions, limitations and driver support'),
G.ref('https://learn.microsoft.com/sql/t-sql/functions/vector-distance-transact-sql','VECTOR_DISTANCE','Microsoft: metrics and return values'),
G.ref('https://learn.microsoft.com/sql/t-sql/statements/create-vector-index-transact-sql','CREATE VECTOR INDEX','Microsoft: syntax and limitations of the approximate index'),
G.ref('https://learn.microsoft.com/sql/t-sql/functions/vector-search-transact-sql','VECTOR_SEARCH','Microsoft: the table-valued search function'),
G.ref('https://learn.microsoft.com/sql/t-sql/data-types/json-data-type','JSON data type','Microsoft: storage, limits, the modify method and conversions'),
G.ref('https://learn.microsoft.com/sql/t-sql/statements/create-json-index-transact-sql','CREATE JSON INDEX','Microsoft: paths, requirements and supported predicates'),
G.ref('https://learn.microsoft.com/sql/sql-server/editions-and-components-of-sql-server-2025','Editions and supported features of SQL Server 2025','Microsoft: limits by edition'),
G.ref('https://devblogs.microsoft.com/azure-sql/sql-server-2025-embraces-vectors-setting-the-foundation-for-empowering-your-data-with-ai','SQL Server 2025 embraces vectors','Azure SQL blog: the design of the vector features'),
G.ref('https://hub.docker.com/r/microsoft/mssql-server','SQL Server container images','Tags and environment variables'),
G.ref('https://github.com/dotnet/SqlClient','Microsoft.Data.SqlClient','The .NET driver, with SqlVector and json support'),
G.ref('https://github.com/microsoft/DiskANN','DiskANN','The approximate nearest-neighbour algorithm behind the vector index'),
G.ref(REPO,'Sample code for this article','T-SQL batches, lab program, pipeline script and results')])
];
G.save(4,parts)
