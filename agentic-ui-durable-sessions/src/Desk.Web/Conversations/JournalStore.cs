using Microsoft.Data.Sqlite;

namespace Desk.Web.Conversations;

/// <summary>One row of a conversation's journal: an update, or the mark that ends a turn.</summary>
public sealed record JournalRow(long Seq, string Kind, string? Body);

/// <summary>
/// Conversations on disk, in SQLite. A conversation is a journal of what the UI agent was told,
/// in order, plus the latest shared state. The file holds everything that was said and everything
/// the tools returned: treat it as you would treat the data behind those tools.
/// </summary>
public sealed class JournalStore
{
    public const string Update = "update";
    public const string TurnDone = "done";

    private readonly string _connection;

    public JournalStore(string file)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(file))!);
        _connection = new SqliteConnectionStringBuilder { DataSource = file }.ToString();
        Run("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS journal (thread TEXT NOT NULL, seq INTEGER NOT NULL, kind TEXT NOT NULL, body TEXT, PRIMARY KEY (thread, seq));
            CREATE TABLE IF NOT EXISTS state (thread TEXT PRIMARY KEY, body TEXT NOT NULL);
            """);
    }

    public List<JournalRow> Load(string thread)
    {
        using SqliteConnection db = Open();
        using SqliteCommand command = db.CreateCommand();
        command.CommandText = "SELECT seq, kind, body FROM journal WHERE thread = $thread ORDER BY seq";
        command.Parameters.AddWithValue("$thread", thread);
        using SqliteDataReader reader = command.ExecuteReader();
        List<JournalRow> rows = [];
        while (reader.Read())
        {
            rows.Add(new JournalRow(reader.GetInt64(0), reader.GetString(1), reader.IsDBNull(2) ? null : reader.GetString(2)));
        }

        return rows;
    }

    public void Append(string thread, JournalRow row) => Run(
        "INSERT INTO journal (thread, seq, kind, body) VALUES ($thread, $seq, $kind, $body)",
        ("$thread", thread), ("$seq", row.Seq), ("$kind", row.Kind), ("$body", (object?)row.Body ?? DBNull.Value));

    /// <summary>Replaces the rows from a sequence number on with a shorter set that means the same, in one transaction.</summary>
    public void Rewrite(string thread, long fromSeq, IReadOnlyList<JournalRow> rows)
    {
        using SqliteConnection db = Open();
        using SqliteTransaction transaction = db.BeginTransaction();
        Run(db, transaction, "DELETE FROM journal WHERE thread = $thread AND seq >= $seq", ("$thread", thread), ("$seq", fromSeq));
        foreach (JournalRow row in rows)
        {
            Run(db, transaction, "INSERT INTO journal (thread, seq, kind, body) VALUES ($thread, $seq, $kind, $body)",
                ("$thread", thread), ("$seq", row.Seq), ("$kind", row.Kind), ("$body", (object?)row.Body ?? DBNull.Value));
        }

        transaction.Commit();
    }

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
