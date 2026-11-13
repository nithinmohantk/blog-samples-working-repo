namespace ActiveActive.Core;

public enum Strategy
{
    /// <summary>Both regions accept writes. A conflict keeps the later write and says nothing.</summary>
    MultiWriteLastWriterWins,

    /// <summary>Both regions accept writes. A conflict keeps the earlier write and records a compensation for the loser.</summary>
    MultiWriteFirstWriterWins,

    /// <summary>Each slot has a home region. No conflicts, and no writes to a slot while its home is down.</summary>
    SingleWriterPerSlot,

    /// <summary>One primary. The standby is promoted after a delay and has not seen the primary's last unreplicated writes.</summary>
    ActivePassive,
}

public sealed record SimulationResult(
    int Accepted, int RefusedSlotTaken, int RefusedUnavailable, int FailedOver, int Conflicts,
    int SilentlyLost, int Compensated, int AcknowledgedThenNotHeld, int FinalBookings, bool RegionsAgree);

/// <summary>
/// A booking service in two regions on a fixed workload. One attempt arrives per tick at a random region for a
/// random slot; an accepted write reaches the other region <see cref="Lag"/> ticks later; one region is down
/// for a window. The Python sample runs the same model, and the two must print the same numbers.
/// </summary>
public static class BookingSimulation
{
    public const int Slots = 2000;
    public const int Attempts = 2000;
    public const int Lag = 20;
    public const int OutageStart = 800;
    public const int OutageEnd = 920;
    public const int FailoverDelay = 30;

    private readonly record struct Write(int Patient, int Tick, int Region);

    private sealed record Message(int Due, int Sender, int Slot, Write Write);

    public static SimulationResult Run(Strategy strategy, int failedRegion, uint seed = 20261025)
    {
        uint state = seed;
        int Next(int bound)
        {
            state = unchecked(state * 1664525 + 1013904223);
            return (int)((state >> 8) % (uint)bound);
        }

        Dictionary<int, Write>[] view = [[], []];
        List<Message> outbox = [];
        HashSet<int> acknowledged = [];
        int accepted = 0, slotTaken = 0, unavailable = 0, failedOver = 0, conflicts = 0, lost = 0, compensated = 0;
        int primary = 0;
        bool promoted = false;

        bool Up(int region, int tick) => !(region == failedRegion && tick >= OutageStart && tick < OutageEnd);

        void Book(int region, int slot, int patient, int tick)
        {
            if (view[region].ContainsKey(slot))
            {
                slotTaken++;
                return;
            }

            Write write = new(patient, tick, region);
            view[region][slot] = write;
            outbox.Add(new Message(tick + Lag, region, slot, write));
            acknowledged.Add(patient);
            accepted++;
        }

        for (int tick = 0; tick < Attempts || outbox.Count > 0; tick++)
        {
            // Replication: a message is delivered once it is due and both ends are up.
            List<Message> waiting = [];
            foreach (Message message in outbox)
            {
                int receiver = 1 - message.Sender;
                if (message.Due > tick || !Up(message.Sender, tick) || !Up(receiver, tick))
                {
                    waiting.Add(message);
                    continue;
                }

                if (!view[receiver].TryGetValue(message.Slot, out Write local) || local == message.Write)
                {
                    view[receiver][message.Slot] = message.Write;
                    continue;
                }

                int order = (message.Write.Tick, message.Write.Region).CompareTo((local.Tick, local.Region));
                bool incomingWins = strategy == Strategy.MultiWriteLastWriterWins ? order > 0 : order < 0;
                if (incomingWins)
                {
                    // Each conflict is seen from both sides; count it where the local write loses.
                    conflicts++;
                    if (strategy == Strategy.MultiWriteLastWriterWins) { lost++; } else { compensated++; }
                    view[receiver][message.Slot] = message.Write;
                }
            }

            outbox = waiting;

            if (strategy == Strategy.ActivePassive)
            {
                if (!promoted && failedRegion == primary && tick == OutageStart + FailoverDelay)
                {
                    // Promote the standby. Writes the old primary had not shipped are gone.
                    lost += outbox.Count;
                    outbox.Clear();
                    primary = 1 - primary;
                    promoted = true;
                }

                if (promoted && tick == OutageEnd)
                {
                    view[1 - primary] = new Dictionary<int, Write>(view[primary]); // the old primary rejoins as a copy
                }
            }

            if (tick >= Attempts)
            {
                continue;
            }

            int arrival = Next(2), slot = Next(Slots), patient = tick;
            switch (strategy)
            {
                case Strategy.MultiWriteLastWriterWins or Strategy.MultiWriteFirstWriterWins:
                    int target = arrival;
                    if (!Up(target, tick))
                    {
                        target = 1 - arrival;
                        failedOver++;
                    }

                    Book(target, slot, patient, tick);
                    break;
                case Strategy.SingleWriterPerSlot:
                    int home = slot % 2;
                    if (Up(home, tick)) { Book(home, slot, patient, tick); } else { unavailable++; }
                    break;
                default:
                    if (Up(primary, tick)) { Book(primary, slot, patient, tick); } else { unavailable++; }
                    break;
            }
        }

        // Counted a second way: every patient who was told "booked" and does not hold the slot at the end.
        HashSet<int> holders = [.. view[0].Values.Select(w => w.Patient)];
        bool agree = view[0].Count == view[1].Count && view[0].All(pair => view[1].TryGetValue(pair.Key, out Write other) && other == pair.Value);
        return new SimulationResult(accepted, slotTaken, unavailable, failedOver, conflicts, lost, compensated,
            acknowledged.Count(patient => !holders.Contains(patient)), view[0].Count, agree);
    }
}
