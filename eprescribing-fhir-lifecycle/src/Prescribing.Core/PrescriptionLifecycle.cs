namespace Prescribing.Core;

/// <summary>Where a prescription is in its life. Each value corresponds to one combination of FHIR statuses.</summary>
public enum PrescriptionState
{
    /// <summary>MedicationRequest active, Task requested: any pharmacy may claim it.</summary>
    Open,

    /// <summary>MedicationRequest active, Task accepted with an owner: one pharmacy is dispensing.</summary>
    Claimed,

    /// <summary>MedicationRequest completed, Task completed: every authorised supply has been made.</summary>
    Completed,

    /// <summary>MedicationRequest cancelled, or stopped if a supply was already made; Task cancelled: withdrawn by the prescriber.</summary>
    Cancelled,

    /// <summary>MedicationRequest stopped, Task cancelled: the validity period ended with supplies outstanding.</summary>
    Expired,
}

public enum Refusal
{
    None,
    AlreadyClaimed,
    NotClaimed,
    ClaimedByAnotherPharmacy,
    NoSuppliesRemaining,
    OutsideValidityPeriod,
    NotYetExpired,
    Closed,
}

/// <summary>Everything the rules need to know. Nothing clinical, and nothing that identifies the patient.</summary>
public sealed record Prescription(
    PrescriptionState State, string? ClaimedBy, int SuppliesAllowed, int SuppliesMade, DateTimeOffset ValidFrom, DateTimeOffset ValidUntil)
{
    public int SuppliesRemaining => SuppliesAllowed - SuppliesMade;
}

public abstract record Command
{
    public sealed record Claim(string Pharmacy) : Command;

    public sealed record Release(string Pharmacy) : Command;

    /// <summary>One supply handed to the patient. The dispense id makes a repeated submission harmless.</summary>
    public sealed record Dispense(string Pharmacy, string DispenseId) : Command;

    public sealed record Cancel(string Prescriber, string Reason) : Command;

    public sealed record Expire : Command;
}

public sealed record Decision(Refusal Refusal, Prescription Next)
{
    public bool Accepted => Refusal == Refusal.None;
}

/// <summary>
/// The rules, as one pure function: the current prescription, a command and the time go in; either a refusal
/// or the next prescription comes out. No I/O and no FHIR, so every state and command pair can be tested, and
/// the same function decides in the prescriber's system, the pharmacy's and the service between them.
/// </summary>
public static class PrescriptionLifecycle
{
    public static Decision Decide(Prescription current, Command command, DateTimeOffset now)
    {
        Decision Refuse(Refusal why) => new(why, current);
        Decision Accept(Prescription next) => new(Refusal.None, next);
        bool inValidity = now >= current.ValidFrom && now <= current.ValidUntil;

        if (current.State is PrescriptionState.Completed or PrescriptionState.Cancelled or PrescriptionState.Expired)
        {
            return Refuse(Refusal.Closed);
        }

        switch (command)
        {
            case Command.Claim claim:
                if (current.State == PrescriptionState.Claimed) { return Refuse(Refusal.AlreadyClaimed); }
                if (!inValidity) { return Refuse(Refusal.OutsideValidityPeriod); }
                if (current.SuppliesRemaining <= 0) { return Refuse(Refusal.NoSuppliesRemaining); }
                return Accept(current with { State = PrescriptionState.Claimed, ClaimedBy = claim.Pharmacy });

            case Command.Release release:
                if (current.State != PrescriptionState.Claimed) { return Refuse(Refusal.NotClaimed); }
                if (current.ClaimedBy != release.Pharmacy) { return Refuse(Refusal.ClaimedByAnotherPharmacy); }
                return Accept(current with { State = PrescriptionState.Open, ClaimedBy = null });

            case Command.Dispense dispense:
                if (current.State != PrescriptionState.Claimed) { return Refuse(Refusal.NotClaimed); }
                if (current.ClaimedBy != dispense.Pharmacy) { return Refuse(Refusal.ClaimedByAnotherPharmacy); }
                if (!inValidity) { return Refuse(Refusal.OutsideValidityPeriod); }
                if (current.SuppliesRemaining <= 0) { return Refuse(Refusal.NoSuppliesRemaining); }
                int made = current.SuppliesMade + 1;
                return Accept(current with
                {
                    SuppliesMade = made,
                    ClaimedBy = null,
                    State = made == current.SuppliesAllowed ? PrescriptionState.Completed : PrescriptionState.Open,
                });

            case Command.Cancel:
                // A prescriber may withdraw a prescription at any point before it is closed, claimed or not.
                // A pharmacy that was about to dispense finds out when its own write is refused.
                return Accept(current with { State = PrescriptionState.Cancelled, ClaimedBy = null });

            case Command.Expire:
                if (now <= current.ValidUntil) { return Refuse(Refusal.NotYetExpired); }
                return Accept(current with { State = PrescriptionState.Expired, ClaimedBy = null });

            default:
                throw new ArgumentOutOfRangeException(nameof(command));
        }
    }
}
