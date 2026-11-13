namespace Booking.Core;

public interface IEhrGateway
{
    /// <summary>
    /// Records the appointment in the EHR. Must be safe to call more than once for the same event:
    /// delivery is at least once, so the gateway is where "exactly once" has to be made true.
    /// </summary>
    Task<EhrOutcome> RecordAppointmentAsync(AppointmentEvent appointment, CancellationToken cancellationToken);
}

public sealed record EhrOutcome(bool Created, string EhrAppointmentId);

public sealed record DispatchReport(int Delivered, int Failed, int SkippedCircuitOpen);

/// <summary>
/// Moves booked appointments from the outbox to the EHR. An event leaves the outbox only after the EHR has
/// confirmed it. A failure leaves it in place for the next pass, and a failing EHR opens the circuit.
/// </summary>
public sealed class OutboxDispatcher(BookingLedger ledger, IEhrGateway ehr, CircuitBreaker breaker, AuditLog audit)
{
    public async Task<DispatchReport> DispatchPendingAsync(CancellationToken cancellationToken = default)
    {
        int delivered = 0, failed = 0, skipped = 0;
        foreach (AppointmentEvent appointment in ledger.PendingEvents())
        {
            if (!breaker.TryEnter())
            {
                skipped++;
                continue;
            }

            try
            {
                EhrOutcome outcome = await ehr.RecordAppointmentAsync(appointment, cancellationToken).ConfigureAwait(false);
                breaker.RecordSuccess();
                ledger.MarkDelivered(appointment.AppointmentId);
                audit.Record("system/ehr-sync", outcome.Created ? "ehr.appointment.created" : "ehr.appointment.already-present", appointment.AppointmentId);
                delivered++;
            }
            catch (Exception error) when (error is (HttpRequestException or TimeoutException or TaskCanceledException) && !cancellationToken.IsCancellationRequested)
            {
                breaker.RecordFailure();
                audit.Record("system/ehr-sync", "ehr.appointment.failed", appointment.AppointmentId);
                failed++;
            }
        }

        return new DispatchReport(delivered, failed, skipped);
    }
}
