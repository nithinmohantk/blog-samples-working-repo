namespace Desk.Core;

public sealed record Refund(string Key, string OrderId, decimal Amount, string Reason, string ApprovedBy);

/// <summary>
/// Stands in for the payment system: the place where a refund really happens.
/// A refund is recorded at most once per key, however many times it is asked for.
/// </summary>
public sealed class Ledger
{
    private readonly Lock _gate = new();
    private readonly Dictionary<string, Refund> _byKey = new(StringComparer.Ordinal);
    private int _attempts;

    /// <summary>How many times a refund was asked for, including repeats.</summary>
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
            return (refund, true);
        }
    }

    public void Clear()
    {
        lock (_gate) { _byKey.Clear(); }
        Interlocked.Exchange(ref _attempts, 0);
    }
}
