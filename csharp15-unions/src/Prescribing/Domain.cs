using System.Text.Json.Serialization;

namespace Prescribing;

public enum PrescriptionStatus { Active, Cancelled, Expired }

/// <summary>A synthetic prescription, reduced to what the dispensing decision needs.</summary>
public sealed record Prescription(
    string Id, string Medication, PrescriptionStatus Status, bool AllergyConflict, string? InteractionWith);

public sealed record Dispensed(string PrescriptionId, string Pharmacy, DateTimeOffset At);

public sealed record Rejected(string PrescriptionId, string Code, string Reason);

public sealed record ReferredToPrescriber(string PrescriptionId, string Question);

/// <summary>
/// What happened when a pharmacy tried to dispense. Exactly one of three things, each with its own data.
/// The classifier lets System.Text.Json tell the cases apart by their property names when reading.
/// </summary>
[JsonUnion(TypeClassifier = typeof(JsonUnionTypeStructuralClassifier))]
public union DispenseOutcome(Dispensed, Rejected, ReferredToPrescriber);
