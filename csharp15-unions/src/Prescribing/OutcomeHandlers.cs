namespace Prescribing;

/// <summary>
/// Three consumers of the outcome. Each switch lists every case and has no discard arm, so adding a case
/// to the union breaks the build here until someone decides what the new case means.
/// </summary>
public static class OutcomeHandlers
{
    public static (int Status, string Message) ToHttp(DispenseOutcome outcome) => outcome switch
    {
        Dispensed d => (200, $"Dispensed at {d.Pharmacy}."),
        Rejected r => (422, r.Reason),
        ReferredToPrescriber q => (202, $"Awaiting the prescriber: {q.Question}"),
        null => throw new InvalidOperationException("An outcome with no value reached the API layer."),
    };

    /// <summary>The status a FHIR Task tracking this dispense would move to.</summary>
    public static string ToTaskStatus(DispenseOutcome outcome) => outcome switch
    {
        Dispensed => "completed",
        Rejected => "rejected",
        ReferredToPrescriber => "on-hold",
        null => throw new InvalidOperationException("An outcome with no value cannot be mapped to a task status."),
    };

    /// <summary>An audit line. ToString on a union prints the union's type name, so the text is built here.</summary>
    public static string ToAuditLine(DispenseOutcome outcome) => outcome switch
    {
        Dispensed d => $"{d.PrescriptionId} dispensed pharmacy={d.Pharmacy} at={d.At:O}",
        Rejected r => $"{r.PrescriptionId} rejected code={r.Code}",
        ReferredToPrescriber q => $"{q.PrescriptionId} referred",
        null => "no outcome",
    };
}
