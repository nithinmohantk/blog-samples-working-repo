using System.Data;
using System.Diagnostics;
using System.Globalization;
using System.Text;
using System.Text.Json;
using Lab;
using Microsoft.Data;
using Microsoft.Data.SqlClient;
using Microsoft.Data.SqlTypes;

// Usage: Lab <folder with the .sql files> <output folder>
// The connection string comes from LAB_SQL_CONNECTION. Everything is created in a database named Lab, which is dropped first.
const int Documents = 50_000, Dimensions = 384, Queries = 50, Orders = 50_000;

CultureInfo.DefaultThreadCurrentCulture = CultureInfo.InvariantCulture;
string sqlFolder = args[0], outFolder = args[1];
Directory.CreateDirectory(outFolder);
Dictionary<string, string> sql = Blocks.Load(sqlFolder);
Dictionary<string, object?> results = [];
int failed = 0, checks = 0;

string connection = Environment.GetEnvironmentVariable("LAB_SQL_CONNECTION") ?? throw new InvalidOperationException("LAB_SQL_CONNECTION is not set.");
using Db master = new(connection);
if (!await master.WaitUntilReadyAsync(TimeSpan.FromMinutes(3)))
{
    Console.WriteLine("The server did not accept a login within three minutes.");
    return 2;
}
master.Run("IF DB_ID('Lab') IS NOT NULL BEGIN ALTER DATABASE Lab SET SINGLE_USER WITH ROLLBACK IMMEDIATE; DROP DATABASE Lab; END");
Must(master.Run("CREATE DATABASE Lab"), "create the database");
using Db db = new(new SqlConnectionStringBuilder(connection) { InitialCatalog = "Lab" }.ConnectionString);

Section("0. The server");
foreach (object?[] row in db.Run("""
    SELECT CAST(SERVERPROPERTY('ProductVersion') AS varchar(40)), CAST(SERVERPROPERTY('ProductLevel') AS varchar(40)),
           CAST(ISNULL(SERVERPROPERTY('ProductUpdateLevel'), 'none') AS varchar(40)), CAST(SERVERPROPERTY('Edition') AS varchar(80)),
           (SELECT compatibility_level FROM sys.databases WHERE name = 'Lab'),
           (SELECT CAST(value AS int) FROM sys.database_scoped_configurations WHERE name = 'PREVIEW_FEATURES')
    """).Rows)
{
    Console.WriteLine($"  version {row[0]}, level {row[1]}, cumulative update {row[2]}, {row[3]}");
    Console.WriteLine($"  database compatibility level {row[4]}, PREVIEW_FEATURES = {row[5]}");
    results["server"] = new { version = row[0], level = row[1], update = row[2], edition = row[3], compatibility = row[4] };
}
Console.WriteLine($"  driver Microsoft.Data.SqlClient {typeof(SqlConnection).Assembly.GetName().Version}");

// ---------------------------------------------------------------------------------------------------------------
Section("1. The vector type");
Check("cosine distance of two perpendicular vectors is 1",
    Near(db.Run("SELECT VECTOR_DISTANCE('cosine', CAST('[1,0]' AS vector(2)), CAST('[0,1]' AS vector(2)))").Scalar, 1.0));
Check("euclidean distance of the same two is the square root of 2",
    Near(db.Run("SELECT VECTOR_DISTANCE('euclidean', CAST('[1,0]' AS vector(2)), CAST('[0,1]' AS vector(2)))").Scalar, Math.Sqrt(2)));
Check("'dot' returns the negative dot product, so smaller is still nearer: [1,2,3] and [4,5,6] give -32",
    Near(db.Run("SELECT VECTOR_DISTANCE('dot', CAST('[1,2,3]' AS vector(3)), CAST('[4,5,6]' AS vector(3)))").Scalar, -32.0));
Observe("1.1", "a vector cast to text", "SELECT CAST(CAST('[1, 2.5, -3]' AS vector(3)) AS varchar(100))");
Observe("1.2", "a float32 vector of 1,998 dimensions", "CREATE TABLE dbo.Wide (id int PRIMARY KEY, e vector(1998)); DROP TABLE dbo.Wide;");
Observe("1.3", "one of 1,999 dimensions", "CREATE TABLE dbo.Wider (id int PRIMARY KEY, e vector(1999));");
Observe("1.4", "three numbers into a vector(2)", "DECLARE @v vector(2) = '[1,2,3]';");
Observe("1.5", "text that is not an array of numbers", "DECLARE @v vector(2) = '[1,\"two\"]';");
Observe("1.6", "comparing two vectors with =", "SELECT CASE WHEN CAST('[1,0]' AS vector(2)) = CAST('[1,0]' AS vector(2)) THEN 1 ELSE 0 END");
Observe("1.7", "a vector as a primary key", "CREATE TABLE dbo.Keyed (e vector(2) NOT NULL PRIMARY KEY);");
Observe("1.8", "a float16 vector, PREVIEW_FEATURES off", "CREATE TABLE dbo.Half (id int PRIMARY KEY, e vector(8, float16)); DROP TABLE dbo.Half;");

Section("2. Loading " + Documents.ToString("N0") + " vectors of " + Dimensions + " dimensions");
Synthetic data = new(20260425);
float[][] vectors = data.Vectors(Documents, Dimensions, clusters: 64, noise: 0.6, out int[] cluster);
Must(db.Run(sql["vector.table"]), "create dbo.Doc");
Stopwatch load = Stopwatch.StartNew();
for (int start = 0; start < Documents; start += 1000)
{
    StringBuilder rows = new("[");
    for (int i = start; i < start + 1000; i++)
    {
        rows.Append(i == start ? "" : ",").Append(CultureInfo.InvariantCulture, $"{{\"id\":{i + 1},\"category\":{cluster[i] % 8},\"title\":\"Document {i + 1}\",\"embedding\":{Synthetic.Json(vectors[i])}}}");
    }
    Must(db.Run(sql["vector.load"], ("@rows", rows.Append(']').ToString())), "load a batch");
}
load.Stop();
Check($"{Documents:N0} rows are in the table", Convert.ToInt32(db.Run("SELECT COUNT(*) FROM dbo.Doc").Scalar) == Documents);
long docKb = Convert.ToInt64(db.Run(sql["json.size"], ("@table", "dbo.Doc")).Scalar);
Console.WriteLine($"  loaded in {load.Elapsed.TotalSeconds:F1} s as JSON text, 1,000 rows per round trip");
Console.WriteLine($"  table size {docKb / 1024.0:F1} MB, {docKb * 1024.0 / Documents:F0} bytes per row; the raw floats are {Dimensions * 4} bytes");
results["vector_load"] = new { rows = Documents, dimensions = Dimensions, seconds = Math.Round(load.Elapsed.TotalSeconds, 1), table_mb = Math.Round(docKb / 1024.0, 1), bytes_per_row = Math.Round(docKb * 1024.0 / Documents) };

Section("3. Exact search, checked against the same arithmetic in C#");
float[][] queries = [.. Enumerable.Range(0, Queries).Select(_ => data.Near(vectors[data.Pick(Documents)], 0.3))];
List<int[]> exactIds = [];
List<double> exactMs = [];
bool agrees = true;
foreach (float[] query in queries)
{
    Outcome exact = Must(db.Run(sql["vector.exact"], ("@q", Synthetic.Json(query))), "exact search");
    exactMs.Add(exact.Milliseconds);
    exactIds.Add([.. exact.Rows.Select(row => Convert.ToInt32(row[0]))]);
    double[] expected = [.. vectors.Select(vector => Synthetic.CosineDistance(query, vector)).Order().Take(10)];
    agrees &= exact.Rows.Count == 10 && exact.Rows.Select((row, i) => Math.Abs(Convert.ToDouble(row[1]) - expected[i]) < 1e-4).All(same => same);
}
Check($"the ten nearest and their distances match a brute-force calculation for all {Queries} queries", agrees);
Outcome scan = db.Run("SET STATISTICS IO ON; " + sql["vector.exact"] + " SET STATISTICS IO OFF;", ("@q", Synthetic.Json(queries[0])));
Console.WriteLine($"  median {Median(exactMs):F0} ms per query over {Documents:N0} rows (slowest {exactMs.Max():F0} ms); one query reads {scan.LogicalReads + scan.LobReads:N0} pages");
results["exact"] = new { median_ms = Math.Round(Median(exactMs)), max_ms = Math.Round(exactMs.Max()), pages = scan.LogicalReads + scan.LobReads };

Section("4. What the driver sees");
(string clr, string type, object? value) = db.Describe("SELECT embedding FROM dbo.Doc WHERE id = 1");
Console.WriteLine($"  a vector column is read as SQL type '{type}', .NET type {clr}");
try
{
    SqlParameter typed = new("@v", SqlDbTypeExtensions.Vector) { Value = new SqlVector<float>(vectors[0]) };
    Outcome distance = db.Run("SELECT VECTOR_DISTANCE('cosine', embedding, @v) FROM dbo.Doc WHERE id = 1", ("@v", typed));
    Console.WriteLine($"  a SqlVector<float> parameter: {distance.Summary}{(distance.Ok ? $", distance to its own row {Convert.ToDouble(distance.Scalar):F6}" : "")}");
    bool same = value is SqlVector<float> read && read.Memory.Span.SequenceEqual(vectors[0]);
    Check("the 384 floats read back through the driver are bit-for-bit the ones that were sent as text", same);
}
catch (Exception error) when (error is not SqlException)
{
    Console.WriteLine($"  typed vector parameter failed in the driver: {error.GetType().Name}: {error.Message}");
}

Section("5. The vector index, a preview feature");
long beforeIndexKb = Convert.ToInt64(db.Run("SELECT SUM(used_page_count) * 8 FROM sys.dm_db_partition_stats").Scalar);
ObserveAs("5.1", "CREATE VECTOR INDEX with PREVIEW_FEATURES off", sql["vector.index"], "CREATE VECTOR INDEX IX_Doc_embedding ON dbo.Doc (embedding) WITH (METRIC = 'cosine', TYPE = 'DiskANN');");
Observe("5.2", "turn the preview features on for this database", "ALTER DATABASE SCOPED CONFIGURATION SET PREVIEW_FEATURES = ON;");
Outcome build = ObserveAs("5.3", "CREATE VECTOR INDEX again", sql["vector.index"], "CREATE VECTOR INDEX IX_Doc_embedding ON dbo.Doc (embedding) WITH (METRIC = 'cosine', TYPE = 'DiskANN');");
if (build.Ok)
{
    long afterIndexKb = Convert.ToInt64(db.Run("SELECT SUM(used_page_count) * 8 FROM sys.dm_db_partition_stats").Scalar);
    Console.WriteLine($"  built in {build.Milliseconds / 1000:F1} s; the database grew by {(afterIndexKb - beforeIndexKb) / 1024.0:F1} MB");
    List<double> annMs = [], recall = [];
    Outcome first = db.Run(sql["vector.search"], ("@q", Synthetic.Json(queries[0])));
    Console.WriteLine($"  VECTOR_SEARCH: {first.Summary}");
    if (first.Ok)
    {
        for (int i = 0; i < Queries; i++)
        {
            Outcome approximate = Must(db.Run(sql["vector.search"], ("@q", Synthetic.Json(queries[i]))), "approximate search");
            annMs.Add(approximate.Milliseconds);
            recall.Add(approximate.Rows.Select(row => Convert.ToInt32(row[0])).Intersect(exactIds[i]).Count() / 10.0);
        }
        Outcome pages = db.Run("SET STATISTICS IO ON; " + sql["vector.search"] + " SET STATISTICS IO OFF;", ("@q", Synthetic.Json(queries[0])));
        Console.WriteLine($"  median {Median(annMs):F1} ms per query (slowest {annMs.Max():F1} ms); one query reads {pages.LogicalReads + pages.LobReads:N0} pages");
        Console.WriteLine($"  recall against the exact answer: mean {recall.Average():P1}, worst query {recall.Min():P0}, {recall.Count(r => r == 1.0)} of {Queries} queries returned exactly the true ten");
        results["index"] = new { build_seconds = Math.Round(build.Milliseconds / 1000, 1), grew_mb = Math.Round((afterIndexKb - beforeIndexKb) / 1024.0, 1), median_ms = Math.Round(Median(annMs), 1), max_ms = Math.Round(annMs.Max(), 1), pages = pages.LogicalReads + pages.LobReads, mean_recall = Math.Round(recall.Average(), 4), worst_recall = recall.Min(), perfect = recall.Count(r => r == 1.0) };

        int category = cluster[0] % 8;
        int[] filteredCounts = [.. Enumerable.Range(0, Queries).Select(i => db.Run(sql["vector.search.filtered"], ("@q", Synthetic.Json(queries[i])), ("@category", category)).Rows.Count)];
        int[] exactCounts = [.. Enumerable.Range(0, Queries).Select(i => db.Run(sql["vector.exact.filtered"], ("@q", Synthetic.Json(queries[i])), ("@category", category)).Rows.Count)];
        Console.WriteLine($"  with WHERE category = {category}: the exact query returned 10 rows for {exactCounts.Count(c => c == 10)} of {Queries} queries;");
        Console.WriteLine($"    the index query returned 10 for {filteredCounts.Count(c => c == 10)}, fewer for {filteredCounts.Count(c => c is > 0 and < 10)}, and none for {filteredCounts.Count(c => c == 0)}");
        results["filtered"] = new { category, index_full = filteredCounts.Count(c => c == 10), index_partial = filteredCounts.Count(c => c is > 0 and < 10), index_empty = filteredCounts.Count(c => c == 0) };
    }
    Console.WriteLine("  writes to the table while the index exists:");
    string extra = Synthetic.Json(data.Near(vectors[1], 0.3));
    Observe("5.4", "insert a row", "INSERT INTO dbo.Doc (id, category, title, embedding) VALUES (900001, 1, N'New', CAST(@q AS vector(384)));", ("@q", extra));
    Observe("5.5", "update a column that is not the vector", "UPDATE dbo.Doc SET title = N'Renamed' WHERE id = 2;");
    Observe("5.6", "update the vector", "UPDATE dbo.Doc SET embedding = CAST(@q AS vector(384)) WHERE id = 2;", ("@q", extra));
    Observe("5.7", "delete a row", "DELETE FROM dbo.Doc WHERE id = 3;");
    ObserveAs("5.8", "drop the index", sql["vector.drop.index"], "DROP INDEX IX_Doc_embedding ON dbo.Doc;");
    Observe("5.9", "insert a row once the index is gone", "INSERT INTO dbo.Doc (id, category, title, embedding) VALUES (900002, 1, N'New', CAST(@q AS vector(384)));", ("@q", extra));
}
Observe("5.10", "a float16 vector, PREVIEW_FEATURES on", "CREATE TABLE dbo.Half (id int PRIMARY KEY, e vector(8, float16)); DROP TABLE dbo.Half;");
Observe("5.11", "turn the preview features off again", "ALTER DATABASE SCOPED CONFIGURATION SET PREVIEW_FEATURES = OFF;");

// ---------------------------------------------------------------------------------------------------------------
Section("6. The json type");
Observe("6.1", "an object", "DECLARE @j json = '{\"a\": 1,  \"b\": [true, null]}'; SELECT CAST(@j AS nvarchar(100));");
Observe("6.2", "a bare scalar", "DECLARE @j json = 'true';");
Observe("6.3", "text that is not JSON", "DECLARE @j json = '{\"a\": }';");
Observe("6.4", "a repeated key", "DECLARE @j json = '{\"a\": 1, \"a\": 2}'; SELECT CAST(@j AS nvarchar(100));");
Observe("6.5", "a number with more digits than a double holds", "DECLARE @j json = '{\"n\": 12345678901234567890.123456789}'; SELECT CAST(@j AS nvarchar(100));");
Observe("6.6", "key order and trailing zeros", "DECLARE @j json = '{\"b\": 1.50, \"a\": 2}'; SELECT CAST(@j AS nvarchar(100));");
Observe("6.7", "comparing two json values with =", "DECLARE @a json = '{}', @b json = '{}'; SELECT CASE WHEN @a = @b THEN 1 ELSE 0 END;");
Observe("6.8", "ORDER BY a json column", "SELECT j FROM (VALUES (CAST('{}' AS json))) AS t(j) ORDER BY j;");
Observe("6.9", "JSON_VALUE with RETURNING", "DECLARE @j json = '{\"total\": 12.50}'; SELECT JSON_VALUE(@j, '$.total' RETURNING decimal(9, 2));");
Observe("6.10", "JSON_CONTAINS, PREVIEW_FEATURES off", "DECLARE @j json = '{\"c\": \"IE\"}'; SELECT JSON_CONTAINS(@j, 'IE', '$.c');");

Section("7. " + Orders.ToString("N0") + " order documents stored four ways");
Must(db.Run(sql["json.tables"]), "create the order tables");
for (int start = 1; start <= Orders; start += 5000)
{
    string batch = "[" + string.Join(",", Enumerable.Range(start, 5000).Select(data.Order)) + "]";
    Must(db.Run(sql["json.load"], ("@rows", batch)), "load orders");
}
Outcome copy = Must(db.Run(sql["json.copy"]), "copy the documents into the other three tables");
Dictionary<string, long> sizes = [];
foreach ((string table, string label) in new[] { ("dbo.OrdersN", "nvarchar(max)"), ("dbo.OrdersV", "varchar(max), UTF-8"), ("dbo.OrdersJ", "json") })
{
    sizes[label] = Convert.ToInt64(db.Run(sql["json.size"], ("@table", table)).Scalar);
    Console.WriteLine($"  {label,-20} {sizes[label] / 1024.0,6:F1} MB   {sizes[label] * 1024.0 / Orders,5:F0} bytes per document");
}
int textBytes = Convert.ToInt32(db.Run("SELECT AVG(DATALENGTH(doc)) FROM dbo.OrdersV").Scalar);
Console.WriteLine($"  the documents average {textBytes} bytes as UTF-8 text");
results["json_storage_kb"] = sizes;
(string jsonClr, string jsonType, _) = db.Describe("SELECT doc FROM dbo.OrdersJ WHERE id = 1");
Console.WriteLine($"  a json column is read as SQL type '{jsonType}', .NET type {jsonClr}");

Section("8. Finding the orders for one country, about 1 in 200");
Dictionary<string, object> lookups = [];
Outcome Lookup(string label, string block)
{
    List<double> times = [.. Enumerable.Range(0, 7).Select(_ => db.Run(sql[block]).Milliseconds)];
    Outcome io = Must(db.Run("SET STATISTICS IO ON; " + sql[block] + " SET STATISTICS IO OFF;"), label);
    Console.WriteLine($"  {label,-44} {Convert.ToInt32(io.Rows[0][0]),4} orders   median {Median(times),6:F1} ms   {io.LogicalReads + io.LobReads,6:N0} pages read");
    lookups[label] = new { median_ms = Math.Round(Median(times), 1), pages = io.LogicalReads + io.LobReads };
    return io;
}
Outcome fromText = Lookup("nvarchar(max), no index", "json.query.text");
Outcome fromNative = Lookup("json, no index", "json.query.native");
Must(db.Run(sql["json.computed"]), "add the computed column and its index");
Outcome fromComputed = Lookup("json, computed column with a B-tree index", "json.query.computed");
ObserveAs("8.1", "CREATE JSON INDEX with PREVIEW_FEATURES off", sql["json.index"], "CREATE JSON INDEX IX_OrdersJ_doc ON dbo.OrdersJ (doc) FOR ('$.customer.country', '$.status');");
Outcome? fromIndex = null;
if (db.Run("SELECT 1 FROM sys.indexes WHERE name = 'IX_OrdersJ_doc'").Rows.Count == 0)
{
    Observe("8.2", "turn the preview features on", "ALTER DATABASE SCOPED CONFIGURATION SET PREVIEW_FEATURES = ON;");
    ObserveAs("8.3", "CREATE JSON INDEX again", sql["json.index"], "CREATE JSON INDEX IX_OrdersJ_doc ON dbo.OrdersJ (doc) FOR ('$.customer.country', '$.status');");
}
if (db.Run("SELECT 1 FROM sys.indexes WHERE name = 'IX_OrdersJ_doc'").Rows.Count == 1)
{
    fromIndex = Lookup("json, JSON index", "json.query.native");
    Observe("8.4", "JSON_CONTAINS on the indexed column", "SELECT COUNT(*) FROM dbo.OrdersJ WHERE JSON_CONTAINS(doc, 'MT', '$.customer.country') = 1;");
}
Check("every way of asking returns the same count and the same total",
    new[] { fromNative, fromComputed, fromIndex }.Where(o => o is not null).All(o => Equals(o!.Rows[0][0], fromText.Rows[0][0]) && Equals(o.Rows[0][1], fromText.Rows[0][1])));
results["lookups"] = lookups;

Section("9. Changing one property in every document");
Dictionary<string, object> updates = [];
void Update(string label, string block, string status)
{
    Outcome update = Must(db.Run(sql[block], ("@status", status)), label);
    long logBytes = Convert.ToInt64(update.Rows[0][0]);
    Console.WriteLine($"  {label,-52} {update.Milliseconds / 1000,5:F1} s   {logBytes / 1048576.0,6:F1} MB of log");
    updates[label] = new { seconds = Math.Round(update.Milliseconds / 1000, 1), log_mb = Math.Round(logBytes / 1048576.0, 1) };
}
Update("json, doc.modify(), value of the same length", "json.modify.native", "old");
Update("json, doc.modify(), longer value", "json.modify.native", "shipped-and-invoiced");
Update("json, JSON_MODIFY(), value of the same length", "json.modify.function", "old");
Update("json, JSON_MODIFY(), longer value", "json.modify.function", "shipped-and-invoiced");
Update("nvarchar(max), JSON_MODIFY(), same length", "json.modify.text", "old");
Update("nvarchar(max), JSON_MODIFY(), longer value", "json.modify.text", "shipped-and-invoiced");
Check("after the updates all three tables hold the new status in every document",
    new[] { "OrdersJ", "OrdersC", "OrdersN" }.All(table => Convert.ToInt32(db.Run($"SELECT COUNT(*) FROM dbo.{table} WHERE JSON_VALUE(doc, '$.status') = N'shipped-and-invoiced'").Scalar) == Orders));
results["updates"] = updates;

Section("10. Shaping results");
ObserveAs("10.1", "JSON_OBJECTAGG over a grouped query", sql["json.aggregate"], "SELECT JSON_OBJECTAGG(country : orders) FROM (top five countries by order count)");
Outcome shredded = Must(db.Run(sql["json.shred"]), "OPENJSON over a json column");
Console.WriteLine($"  OPENJSON over the json column: {shredded.Rows.Count} order lines for order 42, first {string.Join(" ", shredded.Rows[0])}");
Observe("10.2", "change an existing nvarchar(max) column to json", "ALTER TABLE dbo.OrdersN DROP CONSTRAINT CK_OrdersN_json; ALTER TABLE dbo.OrdersN ALTER COLUMN doc json NOT NULL;");
Observe("10.3", "the same when one row is not JSON", "CREATE TABLE dbo.Legacy (id int PRIMARY KEY, doc nvarchar(max)); INSERT INTO dbo.Legacy VALUES (1, N'{\"ok\": true}'), (2, N'not json'); ALTER TABLE dbo.Legacy ALTER COLUMN doc json;");

Console.WriteLine($"\n{checks - failed} of {checks} checks passed");
results["checks"] = new { passed = checks - failed, total = checks };
File.WriteAllText(Path.Combine(outFolder, "results.json"), JsonSerializer.Serialize(results, new JsonSerializerOptions { WriteIndented = true }) + "\n");
return failed == 0 ? 0 : 1;

// ---------------------------------------------------------------------------------------------------------------
void Section(string title) => Console.WriteLine($"\n== {title}");

void Check(string what, bool passed)
{
    checks++;
    failed += passed ? 0 : 1;
    Console.WriteLine($"{(passed ? "ok  " : "FAIL")}  {what}");
}

// Runs a statement whose result is the finding, and prints what the server said.
Outcome Observe(string id, string what, string statement, params (string, object)[] parameters) => ObserveAs(id, what, statement, null, parameters);

Outcome ObserveAs(string id, string what, string statement, string? show, params (string, object)[] parameters)
{
    Outcome outcome = db.Run(statement, parameters);
    string text = outcome.Ok
        ? "ok" + (outcome.Rows.Count > 0 ? $" -> {outcome.Rows[0][0]}" : "")
        : outcome.Summary;
    Console.WriteLine($"[{id}] {what}");
    Console.WriteLine($"      {(show ?? statement).ReplaceLineEndings(" ")}");
    Console.WriteLine($"      {(text.Length > 300 ? text[..300] + "..." : text)}");
    return outcome;
}

Outcome Must(Outcome outcome, string what)
{
    if (!outcome.Ok)
    {
        throw new InvalidOperationException($"Could not {what}: {outcome.Summary}");
    }
    return outcome;
}

static bool Near(object? value, double expected) => value is not null && Math.Abs(Convert.ToDouble(value) - expected) < 1e-6;

static double Median(List<double> values)
{
    List<double> sorted = [.. values.Order()];
    return sorted[sorted.Count / 2];
}

/// <summary>The named batches in the .sql files: a block starts at "-- name: x" and ends at the next one.</summary>
static class Blocks
{
    public static Dictionary<string, string> Load(string folder)
    {
        Dictionary<string, string> blocks = [];
        foreach (string file in Directory.GetFiles(folder, "*.sql"))
        {
            string? name = null;
            StringBuilder text = new();
            foreach (string line in File.ReadLines(file))
            {
                if (line.StartsWith("-- name: ", StringComparison.Ordinal))
                {
                    if (name is not null) { blocks[name] = text.ToString().Trim(); }
                    name = line[9..].Trim();
                    text.Clear();
                }
                else if (name is not null)
                {
                    text.AppendLine(line);
                }
            }
            if (name is not null) { blocks[name] = text.ToString().Trim(); }
        }
        return blocks;
    }
}
