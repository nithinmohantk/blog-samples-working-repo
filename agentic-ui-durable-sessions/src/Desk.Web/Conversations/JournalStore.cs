using Microsoft.Data.Sqlite;

namespace Desk.Web.Conversations;

/// <summary>One row of a conversation's journal: an update, or the mark that ends a turn. The database numbers the rows.</summary>
public sealed record JournalRow(long Id, string Turn, string Kind, string? Body);

/// <summary>
/// Conversations on disk, in SQLite. A conversation is a journal of what the UI agent was told,
/// in order, plus the latest shared state. The file holds everything that was said and everything
/// the tools returned: treat it as you would treat the data behind those tools.
/// </summary>
public sealed class JournalStore
{
    public const string Update = "update";
    public const string TurnDone = "done";

    private const string Insert = "INSERT INTO journal (thread, turn, kind, body) VALUES ($thread, $turn, $kind, $body)";
    private readonly string _connection;

    public JournalStore(string file)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(file))!);
        _connection = new SqliteConnectionStringBuilder { DataSource = file }.ToString();
        Run("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS journal (id INTEGER PRIMARY KEY AUTOINCREMENT, thread TEXT NOT NULL, turn TEXT NOT NULL, kind TEXT NOT NULL, body TEXT);
            CREATE INDEX IF NOT EXISTS journal_thread ON journal (thread, id);
            CREATE TABLE IF NOT EXISTS state (thread TEXT PRIMARY KEY, body TEXT NOT NULL);
            """);
    }

    public List<JournalRow> Load(string thread)
    {
        using SqliteConnection db = Open();
        using SqliteCommand command = db.CreateCommand();
        command.CommandText = "SELECT id, turn, kind, body FROM journal WHERE thread = $thread ORDER BY id";
        command.Parameters.AddWithValue("$thread", thread);
        using SqliteDataReader reader = command.ExecuteReader();
        List<JournalRow> rows = [];
        while (reader.Read())
        {
            rows.Add(new JournalRow(reader.GetInt64(0), reader.GetString(1), reader.GetString(2), reader.IsDBNull(3) ? null : reader.GetString(3)));
        }

        return rows;
    }

    /// <summary>Adds one row at the end. Two pages on the same conversation can both do this: the database orders them.</summary>
    public void Append(string thread, string turn, string kind, string? body) => Run(Insert,
        ("$thread", thread), ("$turn", turn), ("$kind", kind), ("$body", (object?)body ?? DBNull.Value));

    /// <summary>Replaces every row of one turn with a final set, in one transaction.</summary>
    public void ReplaceTurn(string thread, string turn, IReadOnlyList<(string Kind, string? Body)> rows)
    {
        using SqliteConnection db = Open();
        using SqliteTransaction transaction = db.BeginTransaction();
        Run(db, transaction, "DELETE FROM journal WHERE thread = $thread AND turn = $turn", ("$thread", thread), ("$turn", turn));
        foreach ((string kind, string? body) in rows)
        {
            Run(db, transaction, Insert, ("$thread", thread), ("$turn", turn), ("$kind", kind), ("$body", (object?)body ?? DBNull.Value));
        }

        transaction.Commit();
    }

    /// <summary>For tests: drops the rows of a conversation from one row on, as if the page had gone at that point.</summary>
    public void Truncate(string thread, long fromId) => Run("DELETE FROM journal WHERE thread = $thread AND id >= $id", ("$thread", thread), ("$id", fromId));

    public string? LoadState(string thread)
    {
        using SqliteConnection db = Open();
        using SqliteCommand command = db.CreateCommand();
        command.CommandText = "SELECT body FROM state WHERE thread = $thread";
        command.Parameters.AddWithValue("$thread", thread);
        return command.ExecuteScalar() as string;
    }

    public void SaveState(string thread, string body) => Run(
        "INSERT INTO state (thread, body) VALUES ($thread, $body) ON CONFLICT (thread) DO UPDATE SET body = excluded.body",
        ("$thread", thread), ("$body", body));

    /// <summary>Rows and characters stored for a conversation, for the lab.</summary>
    public (long Rows, long Characters) Size(string thread)
    {
        using SqliteConnection db = Open();
        using SqliteCommand command = db.CreateCommand();
        command.CommandText = "SELECT COUNT(*), COALESCE(SUM(LENGTH(body)), 0) FROM journal WHERE thread = $thread";
        command.Parameters.AddWithValue("$thread", thread);
        using SqliteDataReader reader = command.ExecuteReader();
        reader.Read();
        return (reader.GetInt64(0), reader.GetInt64(1));
    }

    private void Run(string sql, params (string Name, object Value)[] parameters)
    {
        using SqliteConnection db = Open();
        Run(db, null, sql, parameters);
    }

    private static void Run(SqliteConnection db, SqliteTransaction? transaction, string sql, params (string Name, object Value)[] parameters)
    {
        using SqliteCommand command = db.CreateCommand();
        command.Transaction = transaction;
        command.CommandText = sql;
        foreach ((string name, object value) in parameters)
        {
            command.Parameters.AddWithValue(name, value);
        }

        command.ExecuteNonQuery();
    }

    private SqliteConnection Open()
    {
        SqliteConnection db = new(_connection);
        db.Open();
        return db;
    }
}
