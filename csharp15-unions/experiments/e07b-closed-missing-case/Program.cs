Outcome outcome = new Rejected("rx-1", "interaction");
Console.WriteLine(outcome switch { Dispensed d => "dispensed", Rejected r => "rejected" });

public closed record class Outcome(string PrescriptionId);
public sealed record Dispensed(string PrescriptionId, string Pharmacy) : Outcome(PrescriptionId);
public sealed record Rejected(string PrescriptionId, string Reason) : Outcome(PrescriptionId);
public sealed record Referred(string PrescriptionId, string Question) : Outcome(PrescriptionId);
