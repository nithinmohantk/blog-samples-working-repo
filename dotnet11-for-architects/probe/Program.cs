// Prints the public shape of the .NET 11 APIs the sample uses, read from the installed runtime.
using System.Reflection;

string[] typeNames =
[
    "System.IO.Compression.ZstandardStream, System.IO.Compression",
    "System.IO.Compression.ZstandardStream, System.IO.Compression.Zstandard",
    "System.IO.Compression.ZstandardEncoder, System.IO.Compression",
    "System.IO.Compression.ZstandardCompressionOptions, System.IO.Compression",
    "System.Diagnostics.ProcessTextOutput, System.Diagnostics.Process",
    "System.Diagnostics.ProcessExitStatus, System.Diagnostics.Process",
    "System.Runtime.CompilerServices.UnionAttribute, System.Runtime",
    "System.Runtime.CompilerServices.IUnion, System.Runtime",
    "System.Text.Json.Serialization.JsonUnionAttribute, System.Text.Json",
    "System.IO.StringStream, System.Runtime",
    "System.IO.ReadOnlyMemoryStream, System.Runtime",
    "System.ComponentModel.DataAnnotations.AsyncValidationAttribute, System.ComponentModel.Annotations",
];
foreach (string name in typeNames)
{
    Type? type = Type.GetType(name);
    Console.WriteLine($"\n## {name}: {(type is null ? "NOT FOUND" : type.Assembly.GetName().Name)}");
    if (type is null) { continue; }
    foreach (MemberInfo member in type.GetMembers(BindingFlags.Public | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly))
    {
        Console.WriteLine("  " + member);
    }
}

void Methods(Type type, params string[] names)
{
    Console.WriteLine($"\n## {type.FullName}");
    foreach (MethodInfo method in type.GetMethods(BindingFlags.Public | BindingFlags.Static | BindingFlags.Instance).Where(m => names.Contains(m.Name)))
    {
        Console.WriteLine("  " + method);
    }
}

Methods(typeof(Enumerable), "FullJoin", "LeftJoin");
Methods(typeof(System.Text.Json.JsonSerializer), "SerializeAsyncEnumerable");
Methods(typeof(System.Diagnostics.Process), "Run", "RunAsync", "RunAndCaptureText", "RunAndCaptureTextAsync");
Methods(typeof(System.ComponentModel.DataAnnotations.Validator), "ValidateObjectAsync", "TryValidateObjectAsync");
Console.WriteLine($"\nRuntime: {System.Runtime.InteropServices.RuntimeInformation.FrameworkDescription}");
