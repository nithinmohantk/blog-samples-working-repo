namespace ActiveActive.Core;

public sealed record RegionState(bool DatabaseReachable, bool AcceptingWrites, TimeSpan ReplicationLag, bool Draining);

public sealed record ReadinessVerdict(bool Ready, string Reason);

/// <summary>
/// What the global load balancer's health probe is told. The rule that matters: a region does not take
/// itself out of rotation for a problem every region shares. Replication lag is reported and alerted on,
/// and is not a reason to fail the probe, because both regions see the same lag and would both leave.
/// </summary>
public static class Readiness
{
    public static ReadinessVerdict Evaluate(RegionState state)
    {
        if (state.Draining)
        {
            return new ReadinessVerdict(false, "draining for a deployment or a drill");
        }

        if (!state.DatabaseReachable)
        {
            return new ReadinessVerdict(false, "regional database endpoint unreachable");
        }

        if (!state.AcceptingWrites)
        {
            return new ReadinessVerdict(false, "regional database is not accepting writes");
        }

        return new ReadinessVerdict(true, state.ReplicationLag > TimeSpan.FromSeconds(30)
            ? "ready; replication lag is high and should alert"
            : "ready");
    }
}
