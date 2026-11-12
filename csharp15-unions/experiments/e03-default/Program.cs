Outcome[] slots = new Outcome[1];
Outcome empty = slots[0];
Console.WriteLine("default.Value is null: " + (empty.Value is null));
Console.WriteLine("with null arm: " + (empty switch { Dispensed => "d", Rejected => "r", Referred => "q", null => "no outcome" }));
try { Console.WriteLine(empty switch { Dispensed => "d", Rejected => "r", Referred => "q" }); }
catch (Exception ex) { Console.WriteLine("without null arm: " + ex.GetType().FullName + ": " + ex.Message); }
Outcome? none = null;
Console.WriteLine("nullable wrapper: " + (none switch { Dispensed => "d", Rejected => "r", Referred => "q", null => "null" }));

public sealed record Dispensed(string PrescriptionId, string Pharmacy);
public sealed record Rejected(string PrescriptionId, string Reason);
public sealed record Referred(string PrescriptionId, string Question);
public union Outcome(Dispensed, Rejected, Referred);

