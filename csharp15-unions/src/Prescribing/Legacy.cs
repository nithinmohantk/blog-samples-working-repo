namespace Prescribing.Legacy;

/// <summary>
/// The shape this model replaces: one class, a flag, and a nullable field per possibility. Nothing stops a
/// caller reading Pharmacy on a failure, or the code constructing a success that also carries a rejection.
/// </summary>
public sealed class DispenseResult
{
    public bool Success { get; init; }
    public string? Pharmacy { get; init; }
    public DateTimeOffset? At { get; init; }
    public string? RejectionCode { get; init; }
    public string? RejectionReason { get; init; }
    public string? QuestionForPrescriber { get; init; }
}

public static class LegacyDispensing
{
    public static DispenseResult Decide(Prescription prescription, string pharmacy, DateTimeOffset now)
    {
        if (prescription.Status != PrescriptionStatus.Active)
        {
            // A business outcome reported as an exception: every caller needs a try/catch to find out.
            throw new InvalidOperationException($"Prescription {prescription.Id} is {prescription.Status}.");
        }

        if (prescription.AllergyConflict)
        {
            return new DispenseResult { Success = false, RejectionCode = "allergy", RejectionReason = "Allergy conflict." };
        }

        if (prescription.InteractionWith is not null)
        {
            // Is this a success? The flag has two values and there are three outcomes.
            return new DispenseResult { Success = false, QuestionForPrescriber = "Interaction. Confirm or change." };
        }

        return new DispenseResult { Success = true, Pharmacy = pharmacy, At = now };
    }
}
