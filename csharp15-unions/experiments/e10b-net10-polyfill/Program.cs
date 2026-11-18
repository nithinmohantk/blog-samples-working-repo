Outcome outcome = new Dispensed("rx-1", "Main Street");
Console.WriteLine(outcome switch { Dispensed d => "dispensed", Rejected r => "rejected", Referred q => "referred" });
Console.WriteLine(System.Runtime.InteropServices.RuntimeInformation.FrameworkDescription);

public sealed record Dispensed(string PrescriptionId, string Pharmacy);
public sealed record Rejected(string PrescriptionId, string Reason);
public sealed record Referred(string PrescriptionId, string Question);
public union Outcome(Dispensed, Rejected, Referred);

namespace System.Runtime.CompilerServices
{
    [AttributeUsage(AttributeTargets.Class | AttributeTargets.Struct, AllowMultiple = false)]
    public sealed class UnionAttribute : Attribute { }
    public interface IUnion { object? Value { get; } }
}
