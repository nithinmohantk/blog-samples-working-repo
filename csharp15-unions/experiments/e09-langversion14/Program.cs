Outcome outcome = new Dispensed("rx-1", "Main Street");
Console.WriteLine(outcome.Value);

public sealed record Dispensed(string PrescriptionId, string Pharmacy);
public sealed record Rejected(string PrescriptionId, string Reason);
public sealed record Referred(string PrescriptionId, string Question);
public union Outcome(Dispensed, Rejected, Referred);

