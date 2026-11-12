Validated<int> ok = 42;
Validated<int> bad = new Failure("out of range");
Console.WriteLine(Describe(ok) + " / " + Describe(bad));
Console.WriteLine(Half(10) switch { int v => "half is " + v, Failure f => f.Message, null => "nothing" });
static string Describe<T>(Validated<T> v) => v switch { Failure f => "failed: " + f.Message, T value => "value " + value, null => "nothing" };
static Validated<int> Half(int value) => value % 2 == 0 ? value / 2 : new Failure("odd");

public sealed record Failure(string Message);
public union Validated<T>(T, Failure);
