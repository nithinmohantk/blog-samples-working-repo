namespace Prescribing;

public static class Dispensing
{
    /// <summary>Every path returns an outcome. Nothing is thrown for a business result and nothing is null.</summary>
    public static DispenseOutcome Decide(Prescription prescription, string pharmacy, DateTimeOffset now)
    {
        if (prescription.Status == PrescriptionStatus.Cancelled)
        {
            return new Rejected(prescription.Id, "cancelled", "The prescriber cancelled this prescription.");
        }

        if (prescription.Status == PrescriptionStatus.Expired)
        {
            return new Rejected(prescription.Id, "expired", "The prescription is past its validity period.");
        }

        if (prescription.AllergyConflict)
        {
            return new Rejected(prescription.Id, "allergy", $"A recorded allergy conflicts with {prescription.Medication}.");
        }

        if (prescription.InteractionWith is { } other)
        {
            return new ReferredToPrescriber(prescription.Id, $"{prescription.Medication} interacts with {other}. Confirm or change.");
        }

        return new Dispensed(prescription.Id, pharmacy, now);
    }
}
