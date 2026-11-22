using System.Collections.Concurrent;
using Microsoft.Data.Sqlite;

namespace Desk.Agent;

/// <summary>A tool call the server stopped on, waiting for a person.</summary>
public sealed record PendingApproval(string Fingerprint, DateTimeOffset Expires);

/// <summary>Where pending approvals are kept. Taking one removes it, so an approval can be used once.</summary>
public interface IApprovalStore
{
    void Put(string interruptId, PendingApproval approval);

    bool TryTake(string interruptId, out PendingApproval approval);
}

/// <summary>Gone when the process stops. An approval that was waiting can then never be given.</summary>
public sealed class MemoryApprovalStore : IApprovalStore
{
    private readonly ConcurrentDictionary<string, PendingApproval> _pending = new(StringComparer.Ordinal);

    public void Put(string interruptId, PendingApproval approval) => _pending[interruptId] = approval;

    public bool TryTake(string interruptId, out PendingApproval approval) => _pending.TryRemove(interruptId, out approval!);
}

/// <summary>
/// Survives a restart and can be shared by several instances that open the same database.
/// The delete and the read are one statement, so two requests cannot both take the same approval.
/// </summary>
public sealed class SqliteApprovalStore : IApprovalStore
{
    private readonly string _connection;

    public SqliteApprovalStore(string file)
    {
        _connection = new SqliteConnectionStringBuilder { DataSource = file }.ToString();
        using SqliteConnection db = Open();
        using SqliteCommand command = db.CreateCommand();
        command.CommandText = "PRAGMA journal_mode=WAL; CREATE TABLE IF NOT EXISTS approvals (id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, expires INTEGER NOT NULL);";
        command.ExecuteNonQuery();
    }

    public void Put(string interruptId, PendingApproval approval)
    {
        using SqliteConnection db = Open();
        using SqliteCommand command = db.CreateCommand();
        command.CommandText = "INSERT OR REPLACE INTO approvals (id, fingerprint, expires) VALUES ($id, $fingerprint, $expires)";
        command.Parameters.AddWithValue("$id", interruptId);
        command.Parameters.AddWithValue("$fingerprint", approval.Fingerprint);
        command.Parameters.AddWithValue("$expires", approval.Expires.ToUnixTimeMilliseconds());
        command.ExecuteNonQuery();
    }

    public bool TryTake(string interruptId, out PendingApproval approval)
    {
        using SqliteConnection db = Open();
        using SqliteCommand command = db.CreateCommand();
        command.CommandText = "DELETE FROM approvals WHERE id = $id RETURNING fingerprint, expires";
        command.Parameters.AddWithValue("$id", interruptId);
        using SqliteDataReader reader = command.ExecuteReader();
        if (!reader.Read())
        {
            approval = default!;
            return false;
        }

        approval = new PendingApproval(reader.GetString(0), DateTimeOffset.FromUnixTimeMilliseconds(reader.GetInt64(1)));
        return true;
    }

    private SqliteConnection Open()
    {
        SqliteConnection db = new(_connection);
        db.Open();
        return db;
    }
}
