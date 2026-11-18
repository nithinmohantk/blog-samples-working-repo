// Prints the public surface of the packages this sample builds on, as resolved on the day of the run.
using System.Reflection;

string[] wanted = ["Microsoft.AspNetCore.Components.AI", "AGUI.Client", "AGUI.Server", "AGUI.Abstractions", "AGUI.Formatting", "Microsoft.Agents.AI.Hosting.AGUI.AspNetCore"];
string folder = AppContext.BaseDirectory;
foreach (string name in wanted)
{
    string path = Path.Combine(folder, name + ".dll");
    if (!File.Exists(path)) { Console.WriteLine($"## {name}: not in the output folder"); continue; }
    Assembly assembly = Assembly.LoadFrom(path);
    Console.WriteLine($"## {name} {assembly.GetCustomAttribute<AssemblyInformationalVersionAttribute>()?.InformationalVersion}");
    Type[] types;
    try { types = assembly.GetExportedTypes(); } catch (ReflectionTypeLoadException e) { types = e.Types.Where(t => t is not null).ToArray()!; }
    foreach (Type type in types.OrderBy(t => t.FullName))
    {
        Console.WriteLine($"{(type.IsInterface ? "interface" : type.IsEnum ? "enum" : type.IsAbstract && type.IsSealed ? "static class" : type.IsAbstract ? "abstract class" : "class")} {type.FullName}{(type.BaseType is { } b && b != typeof(object) && !type.IsEnum ? " : " + b.Name : "")}");
        if (type.IsEnum) { Console.WriteLine("    " + string.Join(", ", Enum.GetNames(type))); continue; }
        foreach (MemberInfo member in type.GetMembers(BindingFlags.Public | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly).OrderBy(m => m.Name))
        {
            if (member is MethodInfo { IsSpecialName: true }) continue;
            string attributes = string.Join(" ", member.CustomAttributes.Select(a => a.AttributeType.Name.Replace("Attribute", "")).Where(a => a is "Parameter" or "CascadingParameter" or "EditorRequired" or "Experimental").Select(a => $"[{a}]"));
            Console.WriteLine($"    {attributes} {member}".TrimEnd().Replace("    ", "    "));
        }
    }
}
