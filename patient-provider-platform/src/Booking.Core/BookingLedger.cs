namespace Booking.Core;

public enum BookingStatus { Booked, SlotTaken, UnknownSlot }

public sealed record BookingResult(BookingStatus Status, string? AppointmentId);

/// <summary>What the platform asks the EHR to record. References only: no names, no dates of birth.</summary>
public sealed record AppointmentEvent(string AppointmentId, string SlotId, string PatientReference, DateTimeOffset RecordedAt);

/// <summary>
/// The platform's own record of who holds which slot. Booking a slot, writing the appointment and writing the
/// outbox event are one atomic step, so there is never a booked slot with no event, or an event with no booking.
///
/// This class keeps its state in memory behind one lock so the sample runs anywhere. In a deployment the same
/// three writes are one database transaction:
///   UPDATE slot SET status = 'busy' WHERE slot_id = @slot AND status = 'free'   -- zero rows means "taken"
///   INSERT INTO appointment ...;  INSERT INTO outbox ...;  COMMIT
/// The conditional UPDATE is the lock. A cache in front of it is an optimisation and never the decision.
/// </summary>
public sealed class BookingLedger(IEnumerable<string> freeSlots, TimeProvider clock)
{
    private readonly object _transaction = new();
    private readonly HashSet<string> _free = new(freeSlots, StringComparer.Ordinal);
    private readonly HashSet<string> _known = new(freeSlots, StringComparer.Ordinal);
    private readonly Dictionary<string, BookingResult> _byIdempotencyKey = new(StringComparer.Ordinal);
    private readonly List<AppointmentEvent> _outbox = [];
    private readonly HashSet<string> _delivered = new(StringComparer.Ordinal);
    private int _sequence;

    /// <summary>
    /// Books a slot for a patient. The same idempotency key always gets the answer the first call got, so a
    /// client that timed out and retried cannot book twice or be told "taken" about its own booking.
    /// </summary>
    public BookingResult Book(string slotId, string patientReference, string idempotencyKey)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(slotId);
        ArgumentException.ThrowIfNullOrWhiteSpace(patientReference);
        ArgumentException.ThrowIfNullOrWhiteSpace(idempotencyKey);

        lock (_transaction)
        {
            if (_byIdempotencyKey.TryGetValue(idempotencyKey, out BookingResult? earlier))
            {
                return earlier;
            }

            BookingResult result;
            if (!_known.Contains(slotId))
            {
                result = new BookingResult(BookingStatus.UnknownSlot, null);
            }
            else if (!_free.Remove(slotId))
            {
                result = new BookingResult(BookingStatus.SlotTaken, null);
            }
            else
            {
                string appointmentId = $"appt-{++_sequence:D6}";
                _outbox.Add(new AppointmentEvent(appointmentId, slotId, patientReference, clock.GetUtcNow()));
                result = new BookingResult(BookingStatus.Booked, appointmentId);
            }

            _byIdempotencyKey[idempotencyKey] = result;
            return result;
        }
    }

    /// <summary>Events not yet confirmed by the EHR, oldest first.</summary>
    public IReadOnlyList<AppointmentEvent> PendingEvents()
    {
        lock (_transaction)
        {
            return _outbox.Where(e => !_delivered.Contains(e.AppointmentId)).ToList();
        }
    }

    public void MarkDelivered(string appointmentId)
    {
        lock (_transaction)
        {
            _delivered.Add(appointmentId);
        }
    }
}
