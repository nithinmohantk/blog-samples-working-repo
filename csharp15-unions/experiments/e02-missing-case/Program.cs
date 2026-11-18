Outcome outcome = new Rejected("rx-1", "interaction");
string text = outcome switch { Dispensed d => "dispensed", Rejected r => "rejected" };
Console.WriteLine(text);

public sealed record Dispensed(string PrescriptionId, string Pharmacy);
public sealed record Rejected(string PrescriptionId, string Reason);
public sealed record Referred(string PrescriptionId, string Question);
public union Outcome(Dispensed, Rejected, Referred);

