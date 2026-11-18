using System.Data;
using System.Diagnostics;
using System.Text.RegularExpressions;
using Microsoft.Data.SqlClient;

namespace Lab;

/// <summary>What one batch did: its rows, or the error the server raised, with the time and the pages it read.</summary>
public sealed record Outcome(bool Ok, int Error, string Message, List<object?[]> Rows, double Milliseconds, long LogicalReads, long LobReads)
{
    public object? Scalar => Rows.Count > 0 && Rows[0].Length > 0 ? Rows[0][0] : null;

    public string Summary => Ok ? "ok" : $"error {Error}: {Message.ReplaceLineEndings(" ")}";
}

/// <summary>One connection for the whole run, so session settings and STATISTICS IO output stay together.</summary>
public sealed partial class Db(string connectionString) : IDisposable
{
    private readonly List<string> _messages = [];
    private SqlConnection? _connection;

    /// <summary>Waits for the server in the container to accept logins.</summary>
    public async Task<bool> WaitUntilReadyAsync(TimeSpan limit)
    {
        Stopwatch waited = Stopwatch.StartNew();
        while (waited.Elapsed < limit)
        {
            try
            {
                Connection();
                return true;
            }
            catch (SqlException)
            {
                _connection?.Dispose();
                _connection = null;
                await Task.Delay(TimeSpan.FromSeconds(2));
            }
        }
        return false;
    }

    /// <summary>Runs one batch. A server error is a result, not an exception: several experiments expect one.</summary>
    public Outcome Run(string sql, params (string Name, object Value)[] parameters)
    {
        _messages.Clear();
        List<object?[]> rows = [];
        Stopwatch clock = Stopwatch.StartNew();
        try
        {
            using SqlCommand command = Connection().CreateCommand();
            command.CommandText = sql;
            command.CommandTimeout = 900;
            foreach ((string name, object value) in parameters)
            {
                switch (value)
                {
                    case SqlParameter ready:
                        command.Parameters.Add(ready);
                        break;
                    case string text:
                        command.Parameters.Add(name, SqlDbType.NVarChar, -1).Value = text;
                        break;
                    default:
                        command.Parameters.AddWithValue(name, value);
                        break;
                }
            }
            using SqlDataReader reader = command.ExecuteReader();
            do
            {
                while (reader.Read())
                {
                    object?[] row = new object?[reader.FieldCount];
                    for (int i = 0; i < row.Length; i++)
                    {
                        row[i] = reader.IsDBNull(i) ? null : reader.GetValue(i);
                    }
                    rows.Add(row);
                }
            }
            while (reader.NextResult());
            clock.Stop();
            command.Parameters.Clear();
            return new Outcome(true, 0, "", rows, clock.Elapsed.TotalMilliseconds, Reads(LogicalReads()), Reads(LobLogicalReads()));
        }
        catch (SqlException error)
        {
            return new Outcome(false, error.Number, error.Message, rows, clock.Elapsed.TotalMilliseconds, 0, 0);
        }
    }

    /// <summary>The .NET type and the SQL type name the driver reports for the first column of a query.</summary>
    public (string ClrType, string SqlType, object? Value) Describe(string sql)
    {
        using SqlCommand command = Connection().CreateCommand();
        command.CommandText = sql;
        using SqlDataReader reader = command.ExecuteReader();
        reader.Read();
        return (reader.GetFieldType(0).FullName ?? "?", reader.GetDataTypeName(0), reader.GetValue(0));
    }

    public void Dispose() => _connection?.Dispose();

    private SqlConnection Connection()
    {
        if (_connection is { State: ConnectionState.Open })
        {
            return _connection;
        }
        _connection?.Dispose();
        _connection = new SqlConnection(connectionString);
        _connection.InfoMessage += (_, message) => _messages.Add(message.Message);
        _connection.Open();
        return _connection;
    }

    private long Reads(Regex pattern) =>
        _messages.SelectMany(message => pattern.Matches(message)).Sum(match => long.Parse(match.Groups[1].Value));

    [GeneratedRegex(@"(?<!lob |read-ahead )logical reads (\d+)")]
    private static partial Regex LogicalReads();

    [GeneratedRegex(@"lob logical reads (\d+)")]
    private static partial Regex LobLogicalReads();
}
