using System.Runtime.CompilerServices;
const int N = 1_000_000;
static long Allocated(Action action) { long before = GC.GetAllocatedBytesForCurrentThread(); action(); return GC.GetAllocatedBytesForCurrentThread() - before; }
long sum = 0;
long declared = Allocated(() => { for (int i = 0; i < N; i++) { Amount a = i; sum += a switch { int x => x, decimal d => (long)d, null => 0 }; } });
long custom = Allocated(() => { for (int i = 0; i < N; i++) { AmountNoBox a = i; sum += a switch { int x => x, decimal d => (long)d, null => 0 }; } });
Dose shared = new Dose(5);
long reference = Allocated(() => { for (int i = 0; i < N; i++) { DoseOrNote a = shared; sum += a switch { Dose x => x.Milligrams, Note => 0, null => 0 }; } });
Console.WriteLine($"declared union of int and decimal: {declared / (double)N:F1} bytes per create-and-match");
Console.WriteLine($"hand-written union with TryGetValue: {custom / (double)N:F1} bytes per create-and-match");
Console.WriteLine($"declared union wrapping an existing object: {reference / (double)N:F1} bytes per create-and-match");
Console.WriteLine($"sizes: Amount={Unsafe.SizeOf<Amount>()} AmountNoBox={Unsafe.SizeOf<AmountNoBox>()} bytes");
GC.KeepAlive(sum);

public union Amount(int, decimal);
public sealed record Dose(int Milligrams);
public sealed record Note(string Text);
public union DoseOrNote(Dose, Note);

[Union]
public readonly struct AmountNoBox : IUnion
{
    private readonly decimal _decimal;
    private readonly int _int;
    private readonly byte _tag;
    public AmountNoBox(int value) { _int = value; _tag = 1; }
    public AmountNoBox(decimal value) { _decimal = value; _tag = 2; }
    public object? Value => _tag switch { 1 => _int, 2 => _decimal, _ => null };
    public bool HasValue => _tag != 0;
    public bool TryGetValue(out int value) { value = _int; return _tag == 1; }
    public bool TryGetValue(out decimal value) { value = _decimal; return _tag == 2; }
}
