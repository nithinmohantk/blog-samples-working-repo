using System.Text.Json;

namespace Desk.Core;

public sealed record Refund(string Key, string OrderId, decimal Amount, string Reason);

/// <summary>
/// Stands in for the payment system: the place where a refund really happens.
/// A refund is recorded at most once per key, however many times it is asked for.
/// Give it a file and the refunds outlive the process, as a payment system's records would.
/// </summary>
public sealed class Ledger
{
    private readonly Lock _gate = new();
    private readonly Dictionary<string, Refund> _byKey = new(StringComparer.Ordinal);
    private readonly string? _file;
    private int _attempts;

    public Ledger(string? file = null)
    {
        _file = file;
        if (file is not null && File.Exists(file))
        {
            foreach (string line in File.ReadLines(file).Where(line => line.Length > 0))
            {
                Refund refund = JsonSerializer.Deserialize<Refund>(line)!;
                _byKey[refund.Key] = refund;
            }
        }
    }

    /// <summary>How many times a refund was asked for since this process started, including repeats.</summary>
    public int Attempts => Volatile.Read(ref _attempts);

    public IReadOnlyList<Refund> Refunds
    {
        get { lock (_gate) { return [.. _byKey.Values]; } }
    }

    /// <summary>Records the refund unless one with the same key exists. Returns the stored refund and whether it is new.</summary>
    public (Refund Refund, bool Created) Record(Refund refund)
    {
        Interlocked.Increment(ref _attempts);
        lock (_gate)
        {
            if (_byKey.TryGetValue(refund.Key, out Refund? earlier))
            {
                return (earlier, false);
            }

            _byKey[refund.Key] = refund;
            if (_file is not null)
            {
                File.AppendAllText(_file, JsonSerializer.Serialize(refund) + Environment.NewLine);
            }

            return (refund, true);
        }
    }

    public void Clear()
    {
        lock (_gate)
        {
            _byKey.Clear();
            if (_file is not null)
            {
                File.Delete(_file);
            }
        }

        Interlocked.Exchange(ref _attempts, 0);
    }
}
