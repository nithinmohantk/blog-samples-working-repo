using System.Reflection;
Outcome outcome = new Dispensed("rx-1", "Main Street");
string text = outcome switch { Dispensed d => "dispensed at " + d.Pharmacy, Rejected r => "rejected: " + r.Reason, Referred q => "referred: " + q.Question };
Console.WriteLine(text);
Type t = typeof(Outcome);
Console.WriteLine($"IsValueType={t.IsValueType} implements IUnion={typeof(System.Runtime.CompilerServices.IUnion).IsAssignableFrom(t)}");
Console.WriteLine("attributes: " + string.Join(", ", t.GetCustomAttributes(false).Select(a => a.GetType().Name)));
Console.WriteLine("constructors: " + string.Join(" | ", t.GetConstructors().Select(c => c.ToString())));
Console.WriteLine("instance fields: " + string.Join(" | ", t.GetFields(BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.Public).Select(f => f.FieldType.Name + " " + f.Name)));
Console.WriteLine("public members: " + string.Join(" | ", t.GetMembers(BindingFlags.Instance | BindingFlags.Static | BindingFlags.Public | BindingFlags.DeclaredOnly).Select(m => m.ToString())));
Console.WriteLine("size of struct: " + System.Runtime.CompilerServices.Unsafe.SizeOf<Outcome>());
Console.WriteLine("Value type: " + outcome.Value?.GetType().Name);
Console.WriteLine("is-pattern: " + (outcome is Dispensed { Pharmacy: "Main Street" }));

public sealed record Dispensed(string PrescriptionId, string Pharmacy);
public sealed record Rejected(string PrescriptionId, string Reason);
public sealed record Referred(string PrescriptionId, string Question);
public union Outcome(Dispensed, Rejected, Referred);

