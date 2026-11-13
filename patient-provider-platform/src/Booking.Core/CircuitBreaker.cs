namespace Booking.Core;

public enum CircuitState { Closed, Open, HalfOpen }

/// <summary>
/// Stops calling an EHR that is failing, so a vendor outage or maintenance window costs the platform a queue
/// of pending events and not its worker threads. After <paramref name="openFor"/> one trial call is let through.
/// </summary>
public sealed class CircuitBreaker(int failureThreshold, TimeSpan openFor, TimeProvider clock)
{
    private readonly object _gate = new();
    private int _consecutiveFailures;
    private DateTimeOffset _openedAt;
    private bool _open;
    private bool _trialInFlight;

    public CircuitState State
    {
        get
        {
            lock (_gate)
            {
                if (!_open) { return CircuitState.Closed; }
                return clock.GetUtcNow() - _openedAt >= openFor ? CircuitState.HalfOpen : CircuitState.Open;
            }
        }
    }

    /// <summary>True if a call may be made now. In the half-open state only one caller is admitted.</summary>
    public bool TryEnter()
    {
        lock (_gate)
        {
            if (!_open) { return true; }
            if (clock.GetUtcNow() - _openedAt < openFor || _trialInFlight) { return false; }
            _trialInFlight = true;
            return true;
        }
    }

    public void RecordSuccess()
    {
        lock (_gate)
        {
            _consecutiveFailures = 0;
            _open = false;
            _trialInFlight = false;
        }
    }

    public void RecordFailure()
    {
        lock (_gate)
        {
            _trialInFlight = false;
            if (_open || ++_consecutiveFailures >= failureThreshold)
            {
                _open = true;
                _openedAt = clock.GetUtcNow();
            }
        }
    }
}
