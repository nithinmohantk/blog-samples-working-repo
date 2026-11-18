namespace FhirFacade;

/// <summary>
/// One structured event per access decision: who, on whose record, what, and the result.
/// These events contain a patient identifier, so the sink they go to needs the same protection as the record.
/// </summary>
public static partial class AuditLog
{
    [LoggerMessage(EventId = 1000, Level = LogLevel.Information,
        Message = "AUDIT allowed {Interaction} Observation patient={PatientId} subject={Subject} client={ClientId} basis={Basis} returned={Returned}")]
    public static partial void Allowed(
        ILogger logger, string interaction, string patientId, string subject, string clientId, string basis, int returned);

    [LoggerMessage(EventId = 1001, Level = LogLevel.Warning,
        Message = "AUDIT denied {Interaction} Observation patient={PatientId} subject={Subject} client={ClientId} reason={Reason}")]
    public static partial void Denied(
        ILogger logger, string interaction, string patientId, string subject, string clientId, string reason);
}
