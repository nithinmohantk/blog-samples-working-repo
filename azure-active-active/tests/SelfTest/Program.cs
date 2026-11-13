// Usage: dotnet run -c Release -- [results.json]
using System.Text.Json;
using System.Text.Json.Nodes;
using ActiveActive.Core;

int passed = 0, failed = 0;
void Check(string name, bool condition)
{
    if (condition) { passed++; } else { failed++; }
    Console.WriteLine($"{(condition ? "ok  " : "FAIL")}  {name}");
}

(Strategy Strategy, string Name)[] strategies =
[
    (Strategy.MultiWriteLastWriterWins, "multi_write_last_writer_wins"), (Strategy.MultiWriteFirstWriterWins, "multi_write_first_writer_wins"),
    (Strategy.SingleWriterPerSlot, "single_writer_per_slot"), (Strategy.ActivePassive, "active_passive"),
];
JsonObject results = [];
Dictionary<(string Scenario, Strategy Strategy), SimulationResult> byKey = [];
foreach ((int failedRegion, string scenario) in new[] { (0, "north_fails"), (1, "west_fails") })
{
    JsonObject section = [];
    foreach ((Strategy strategy, string name) in strategies)
    {
        SimulationResult r = BookingSimulation.Run(strategy, failedRegion);
        byKey[(scenario, strategy)] = r;
        section[name] = new JsonObject
        {
            ["accepted"] = r.Accepted, ["refused_slot_taken"] = r.RefusedSlotTaken, ["refused_unavailable"] = r.RefusedUnavailable,
            ["failed_over"] = r.FailedOver, ["conflicts"] = r.Conflicts, ["silently_lost"] = r.SilentlyLost, ["compensated"] = r.Compensated,
            ["acknowledged_then_not_held"] = r.AcknowledgedThenNotHeld, ["final_bookings"] = r.FinalBookings, ["regions_agree"] = r.RegionsAgree,
        };
    }

    results[scenario] = section;
}

Check("every strategy converges: both regions end with the same bookings", byKey.Values.All(r => r.RegionsAgree));
Check("every attempt is accounted for", byKey.Values.All(r => r.Accepted + r.RefusedSlotTaken + r.RefusedUnavailable == BookingSimulation.Attempts));
Check("the independent count matches: taken-back bookings equal lost plus compensated", byKey.Values.All(r => r.AcknowledgedThenNotHeld == r.SilentlyLost + r.Compensated));
foreach (string scenario in new[] { "north_fails", "west_fails" })
{
    SimulationResult lww = byKey[(scenario, Strategy.MultiWriteLastWriterWins)], fww = byKey[(scenario, Strategy.MultiWriteFirstWriterWins)];
    SimulationResult single = byKey[(scenario, Strategy.SingleWriterPerSlot)];
    Check($"{scenario}: multi-write refuses nothing as unavailable", lww.RefusedUnavailable == 0 && fww.RefusedUnavailable == 0);
    Check($"{scenario}: last-writer-wins loses acknowledged bookings without a record", lww.SilentlyLost > 0 && lww.Compensated == 0);
    Check($"{scenario}: first-writer-wins has the same conflicts, each with a compensation", fww.Compensated == lww.SilentlyLost && fww.SilentlyLost == 0);
    Check($"{scenario}: single writer has no conflicts and refuses writes while a home region is down", single.Conflicts == 0 && single.RefusedUnavailable > 0);
}

SimulationResult passiveNorth = byKey[("north_fails", Strategy.ActivePassive)], passiveWest = byKey[("west_fails", Strategy.ActivePassive)];
Check("active-passive: losing the primary refuses writes until failover and loses unreplicated ones", passiveNorth.RefusedUnavailable == BookingSimulation.FailoverDelay && passiveNorth.SilentlyLost > 0);
Check("active-passive: losing the standby costs nothing", passiveWest.RefusedUnavailable == 0 && passiveWest.SilentlyLost == 0);
Check("same seed, same result", BookingSimulation.Run(Strategy.MultiWriteLastWriterWins, 0) == byKey[("north_fails", Strategy.MultiWriteLastWriterWins)]);

IdempotentCommands commands = new();
int executions = 0;
CommandOutcome Book() { Interlocked.Increment(ref executions); return new CommandOutcome(201, """{"booking":"b-1"}""", "north"); }
CommandOutcome first = commands.Execute("key-1", Book), retry = commands.Execute("key-1", Book);
Check("a retried command runs once and returns the first answer", executions == 1 && ReferenceEquals(first, retry));
Parallel.For(0, 64, _ => commands.Execute("key-2", Book));
Check("64 concurrent retries of one command run it once", executions == 2);
IdempotentCommands west = new();
west.Import("key-1", first);
Check("a retry that lands in the other region gets the replicated answer", west.Execute("key-1", () => new CommandOutcome(500, "should not run", "west")) == first);
Check("an empty idempotency key is refused", Throws(() => commands.Execute(" ", Book)));

RegionState healthy = new(DatabaseReachable: true, AcceptingWrites: true, ReplicationLag: TimeSpan.FromSeconds(2), Draining: false);
Check("a healthy region is ready", Readiness.Evaluate(healthy).Ready);
Check("a region that cannot reach its database is not ready", !Readiness.Evaluate(healthy with { DatabaseReachable = false }).Ready);
Check("a region whose database refuses writes is not ready", !Readiness.Evaluate(healthy with { AcceptingWrites = false }).Ready);
Check("a draining region is not ready", !Readiness.Evaluate(healthy with { Draining = true }).Ready);
ReadinessVerdict lagging = Readiness.Evaluate(healthy with { ReplicationLag = TimeSpan.FromMinutes(5) });
Check("high replication lag alerts and does not fail the probe", lagging.Ready && lagging.Reason.Contains("alert"));

if (args.Length > 0) { File.WriteAllText(args[0], results.ToJsonString(new JsonSerializerOptions { WriteIndented = true })); }
Console.WriteLine($"\n{passed} of {passed + failed} checks passed");
return failed == 0 ? 0 : 1;

static bool Throws(Action action) { try { action(); return false; } catch (ArgumentException) { return true; } }
