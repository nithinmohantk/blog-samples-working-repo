using System.Reflection;
using System.Text.RegularExpressions;

// Prints the public surface of the preview packages, so the sample is written against what is there.
Assembly[] assemblies =
[
    typeof(Microsoft.AspNetCore.Components.AI.UIAgent).Assembly,
    typeof(AGUI.Client.AGUIChatClient).Assembly,
    typeof(AGUI.Abstractions.RunAgentInput).Assembly,
    typeof(AGUI.Server.AGUIStreamOptions).Assembly,
];
Regex skip = new("Node$|JsonSerializerContext|EventTypes$|Reasoning|Subagent|Activity|Step(Started|Finished)|Chunk", RegexOptions.Compiled);
foreach (Assembly assembly in assemblies)
{
    Console.WriteLine($"## {assembly.GetName().Name} {assembly.GetCustomAttribute<AssemblyInformationalVersionAttribute>()?.InformationalVersion}");
    foreach (Type type in assembly.GetExportedTypes().OrderBy(t => t.FullName))
    {
        if (skip.IsMatch(type.Name))
        {
            continue;
        }

        string kind = type.IsEnum ? "enum" : type.IsInterface ? "interface" : type.IsAbstract && type.IsSealed ? "static class" : type.IsAbstract ? "abstract class" : "class";
        Console.WriteLine($"{kind} {Name(type)}{(type.BaseType is { } b && b != typeof(object) && b != typeof(ValueType) && b != typeof(Enum) ? " : " + Name(b) : "")}");
        if (type.IsEnum)
        {
            Console.WriteLine("    " + string.Join(", ", Enum.GetNames(type)));
            continue;
        }

        const BindingFlags flags = BindingFlags.Public | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly;
        foreach (ConstructorInfo c in type.GetConstructors(flags))
        {
            Console.WriteLine($"     .ctor({string.Join(", ", c.GetParameters().Select(p => Name(p.ParameterType) + " " + p.Name))})");
        }

        foreach (PropertyInfo p in type.GetProperties(flags))
        {
            string attributes = string.Join(" ", p.GetCustomAttributes().Select(a => a.GetType().Name.Replace("Attribute", "")).Where(n => n is "Parameter" or "CascadingParameter" or "EditorRequired").Select(n => $"[{n}]"));
            Console.WriteLine($"     {attributes} {Name(p.PropertyType)} {p.Name} {{{(p.CanRead ? " get;" : "")}{(p.SetMethod?.IsPublic == true ? " set;" : "")} }}".Replace("      ", "     "));
        }

        foreach (MethodInfo m in type.GetMethods(flags).Where(m => !m.IsSpecialName && m.Name is not ("Equals" or "GetHashCode" or "ToString" or "Deconstruct" or "<Clone>$")))
        {
            Console.WriteLine($"     {(m.IsStatic ? "static " : "")}{Name(m.ReturnType)} {m.Name}{(m.IsGenericMethod ? "<" + string.Join(",", m.GetGenericArguments().Select(a => a.Name)) + ">" : "")}({string.Join(", ", m.GetParameters().Select(p => Name(p.ParameterType) + " " + p.Name))})");
        }
    }
}

static string Name(Type t)
{
    if (t.IsGenericType)
    {
        return t.Name.Split('`')[0] + "<" + string.Join(", ", t.GetGenericArguments().Select(Name)) + ">";
    }

    return t.IsGenericParameter ? t.Name : (t.Namespace is "System" or null ? t.Name : t.FullName!.Replace("Microsoft.AspNetCore.Components.AI.", "").Replace("Microsoft.Extensions.AI.", "").Replace("AGUI.Abstractions.", "").Replace("System.Collections.Generic.", "").Replace("System.Threading.Tasks.", "").Replace("System.Threading.", "").Replace("System.Text.Json.", ""));
}
