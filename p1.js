eval(localStorage.art_H); const G=window.G,p=G.p,h2=G.h2; const I=k=>JSON.parse(localStorage['ev_img'+k]);
window.IM=(k,cap)=>G.img('ZZ'+k,I(k).alt,cap).split('ZZ'+k+'_ID').join(String(I(k).id)).split('ZZ'+k+'_URL').join(I(k).url);
window.SN=(k,a,b)=>{const t=localStorage['ev_code_'+k];const i=t.indexOf(a);const j=t.indexOf(b,i);if(i<0||j<0)throw new Error('marker '+k+' '+(i<0?a:b).slice(0,40));return t.slice(i,j+b.length)};
window.SNIPS=[]; window.snip=(lang,k,a,b)=>{const t=window.SN(k,a,b);window.SNIPS.push([k,t]);return G.code(lang,t)}; const snip=window.snip;
const parts=[
p(`SQL Server 2025 has been generally available since 18 November 2025 and is now at its fourth cumulative update. Two of its additions reach past the database team into application design: a <code>vector</code> type with distance functions and an approximate index, and a native <code>json</code> type with its own index. Between them they raise a question that comes up in most design reviews this year: can the relational database you already run hold the embeddings and the documents too, or do you still need a second store?`),
p(`The answer depends on details that a feature list does not show: what is finished and what is still a preview, what an index does to writes, and what the driver hands your code. This article finds out by running the statements. Every result below comes from the SQL Server 2025 container image, started in a CI pipeline, with a small .NET program that sends T-SQL and records what the server answers.`),
p(`The ORM side of vector search is in <a href="${localStorage.ev_link_efcore}">EF Core 10: Vector Search, LeftJoin/RightJoin, and Full-Text Search on Cosmos DB</a>. This article stays in T-SQL and the driver, where the behaviour is decided.`),
G.callout('info','SCOPE',`SQL Server 2025 build 17.0.4040.1, which is cumulative update 4 with a security update, Developer edition, in the Linux container image. Microsoft.Data.SqlClient 6.1.1 on .NET 10. The data is synthetic: 50,000 vectors of 384 dimensions that are not embeddings from a model, and 50,000 order documents of about 300 bytes. Timings were taken on a CI runner and compare the options with each other. Preview features change between updates, so the status reported here is the status of this build.`),
h2('What is finished and what is behind a switch'),
p(`SQL Server 2025 introduced a database-scoped setting, <code>PREVIEW_FEATURES</code>, that is off by default. Features that shipped before they were finished stay unavailable until someone turns it on for a database. The first thing an architect needs is the list of what falls on which side. This is what the build answered.`),
G.table(['Feature','With the switch off','Notes from the run'],[
['<code>vector(n)</code>, float32','Works','Up to 1,998 dimensions'],
['<code>VECTOR_DISTANCE</code>: cosine, euclidean, dot','Works','Exact search by scanning'],
['<code>CREATE VECTOR INDEX</code>, <code>VECTOR_SEARCH</code>','Error 343','Works with the switch on. Table becomes read-only'],
['<code>vector(n, float16)</code>','Error 195','Works with the switch on'],
['<code>json</code> type, <code>modify()</code>','Works','Objects and arrays only'],
['<code>JSON_VALUE ... RETURNING</code>, <code>JSON_CONTAINS</code>, <code>JSON_OBJECTAGG</code>','Works',''],
['<code>CREATE JSON INDEX</code>','Works','Used by <code>JSON_CONTAINS</code>, not chosen for <code>JSON_VALUE</code>']]),
window.IM('1','The two types and their functions are usable as shipped. Approximate vector search is the part that still needs the preview switch.'),
h2('Architecture: one engine or two'),
p(`There are three places the vectors and documents of an application can live once the system of record is SQL Server. The trade is always the same: one engine means one transaction, one backup and one security model, and a second engine means a better-fitting index and something else to run and keep in step.`),
G.table(['Option','Advantages','Disadvantages and risks','Cost and operations'],[
['Everything in SQL Server 2025','A row and its embedding change in one transaction. Row-level security, auditing, backup and encryption at rest already apply. A join filters by anything','Approximate search is a preview in this build and makes the table read-only. Exact search reads every row','No new service. Index builds and larger rows are paid for in the database you already size'],
['SQL Server plus a dedicated vector store','Mature approximate indexes, filtering inside the search, incremental updates','Two stores to keep consistent. Deletes and permission changes must reach both. A second place where personal data lives','A second service to run, secure, back up and monitor'],
['SQL Server plus a search service','Hybrid keyword and vector ranking, language analysers','The same consistency and data-protection duties, plus an indexing pipeline with its own lag','Per-replica or per-unit pricing, and the pipeline to operate']]),
p(`The measurements that follow are meant to show where the first option stops being enough.`),
h2('A SQL Server container in CI'),
p(`The whole investigation runs in a pipeline, which is also how a team should test its own schema and queries against a new SQL Server version. Three details make it repeatable and safe.`),
p(`The image is pinned. <code>2025-latest</code> moves with every cumulative update, and the tag names carry no dates, so a small script reads each image's build time from the registry and takes the newest one on or before a chosen day.`),
snip('python','pick','def built(tag: str) -> str:','    return get(f"blobs/{manifest[\'config\'][\'digest\']}")["created"]'),
snip('text','r_ver','image    mcr.microsoft.com','size     662 MB'),
p(`The <code>sa</code> password is generated when the script starts, exists only in that shell, and the script fails the run if the value appears in any output file. The connection is encrypted; the certificate is the container's self-signed one, so it is trusted for this test and nowhere else.`),
snip('bash','ci','# A throwaway password for a throwaway container.','export LAB_SQL_CONNECTION="Server=127.0.0.1,14333;User ID=sa;Password=$password;Encrypt=True;TrustServerCertificate=True;Connect Timeout=5"'),
p(`The server takes some seconds to accept logins after the container starts. The program waits for a successful connection, with a limit, before it does anything else.`),
snip('csharp','db','    public async Task<bool> WaitUntilReadyAsync(TimeSpan limit)','        return false;\n    }'),
G.mer(G.MS+`
sequenceDiagram
    participant P as Pipeline
    participant R as Container registry
    participant S as SQL Server container
    participant L as Lab program
    P->>R: Which 2025 tag was built last, on or before the date?
    R-->>P: 2025-CU4-GDR1-ubuntu-22.04
    P->>S: Start with a generated sa password
    P->>L: Run with the connection string
    L->>S: Log in, retrying until ready
    L->>S: Each T-SQL batch
    S-->>L: Rows, or an error number and message
    L-->>P: Transcript and exit code`),
p(`The T-SQL lives in two <code>.sql</code> files as named batches, and the program treats a server error as a result to record, because several of the experiments are expected to fail.`)
];
G.save(1,parts)
