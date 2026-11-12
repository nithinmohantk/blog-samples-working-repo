Outcome outcome = new Rejected("rx-1", "interaction");
Console.WriteLine(outcome switch { Dispensed d => "dispensed at " + d.Pharmacy, Rejected r => "rejected: " + r.Reason, Referred q => "referred: " + q.Question });
Console.WriteLine("shared member without a switch: " + outcome.PrescriptionId);
Console.WriteLine("IsAbstract=" + typeof(Outcome).IsAbstract + " IsClass=" + typeof(Outcome).IsClass);
Console.WriteLine("equality: " + (outcome == new Rejected("rx-1", "interaction")));
Console.WriteLine("json: " + System.Text.Json.JsonSerializer.Serialize(outcome));

public closed record class Outcome(string PrescriptionId);
public sealed record Dispensed(string PrescriptionId, string Pharmacy) : Outcome(PrescriptionId);
public sealed record Rejected(string PrescriptionId, string Reason) : Outcome(PrescriptionId);
public sealed record Referred(string PrescriptionId, string Question) : Outcome(PrescriptionId);
