Outcome a = new Dispensed("rx-1", "Main Street");
Outcome b = new Dispensed("rx-1", "Main Street");
Outcome c = new Rejected("rx-1", "x");
Console.WriteLine("Equals, equal records in two unions: " + a.Equals(b));
Console.WriteLine("Equals, different cases: " + a.Equals(c));
Console.WriteLine("GetHashCode equal: " + (a.GetHashCode() == b.GetHashCode()));
Console.WriteLine("HashSet count for two equal unions: " + new HashSet<Outcome> { a, b }.Count);
Console.WriteLine("EqualityComparer.Default: " + EqualityComparer<Outcome>.Default.Equals(a, b));
Console.WriteLine("ToString: " + a.ToString());
Console.WriteLine("union equals its case value: " + a.Equals(new Dispensed("rx-1", "Main Street")));

public sealed record Dispensed(string PrescriptionId, string Pharmacy);
public sealed record Rejected(string PrescriptionId, string Reason);
public sealed record Referred(string PrescriptionId, string Question);
public union Outcome(Dispensed, Rejected, Referred);

