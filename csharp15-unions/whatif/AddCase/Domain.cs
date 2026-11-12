using System.Text.Json.Serialization;

namespace Prescribing;

public sealed record Dispensed(string PrescriptionId, string Pharmacy, DateTimeOffset At);

public sealed record Rejected(string PrescriptionId, string Code, string Reason);

public sealed record ReferredToPrescriber(string PrescriptionId, string Question);

/// <summary>The new requirement: a pharmacy can supply part of the quantity and owe the rest.</summary>
public sealed record PartiallyDispensed(string PrescriptionId, string Pharmacy, int QuantitySupplied, int QuantityOwed);

[JsonUnion(TypeClassifier = typeof(JsonUnionTypeStructuralClassifier))]
public union DispenseOutcome(Dispensed, Rejected, ReferredToPrescriber, PartiallyDispensed);
