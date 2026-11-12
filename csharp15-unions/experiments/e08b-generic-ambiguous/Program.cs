Validated<Failure> v = new Failure("which case?");
Console.WriteLine(v.Value);
public sealed record Failure(string Message);
public union Validated<T>(T, Failure);
