using System.Collections.Concurrent;

namespace Booking.Core;

public sealed record AuditEntry(DateTimeOffset At, string Actor, string Action, string ResourceId);

/// <summary>
/// Who did what to which record, and when. Entries carry identifiers and never clinical or demographic
/// content, so the audit trail can be retained and searched without becoming a second copy of the record.
/// In a deployment this is an append-only store with its own access control, not application memory.
/// </summary>
public sealed class AuditLog(TimeProvider clock)
{
    private readonly ConcurrentQueue<AuditEntry> _entries = new();

    public void Record(string actor, string action, string resourceId) =>
        _entries.Enqueue(new AuditEntry(clock.GetUtcNow(), actor, action, resourceId));

    public IReadOnlyCollection<AuditEntry> Entries => _entries.ToArray();
}
