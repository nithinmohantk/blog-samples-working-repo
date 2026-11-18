using System.Text.RegularExpressions;

namespace Smart.Backend.Server;

/// <summary>
/// SMART v2 system scopes: system/Patient.rs, system/*.cruds. The letters are create, read, update, delete and
/// search, always in that order. Writing does not imply reading, and reading does not imply searching.
/// </summary>
public sealed partial class ScopeSet
{
    private const string Letters = "cruds";
    private readonly SortedDictionary<string, HashSet<char>> _byType = new(StringComparer.Ordinal);

    [GeneratedRegex(@"^system/(\*|[A-Z][A-Za-z]+)\.(c?r?u?d?s?)$")]
    private static partial Regex Pattern();

    /// <summary>Returns null if any item is not a v2 system scope, including v1 forms such as system/*.read.</summary>
    public static ScopeSet? Parse(string? scope)
    {
        ScopeSet set = new();
        foreach (string item in (scope ?? "").Split(' ', StringSplitOptions.RemoveEmptyEntries))
        {
            Match match = Pattern().Match(item);
            if (!match.Success || match.Groups[2].Length == 0) { return null; }
            set.Add(match.Groups[1].Value, match.Groups[2].Value);
        }
        return set;
    }

    public bool IsEmpty => _byType.Count == 0;

    public bool Allows(string resourceType, char interaction) =>
        (_byType.TryGetValue(resourceType, out HashSet<char>? letters) && letters.Contains(interaction)) || (_byType.TryGetValue("*", out HashSet<char>? any) && any.Contains(interaction));

    /// <summary>What a client may have of what it asked for: each requested item, cut down to the letters it is registered for.</summary>
    public ScopeSet GrantFrom(ScopeSet registered)
    {
        ScopeSet granted = new();
        foreach ((string type, HashSet<char> letters) in _byType)
        {
            // A request for every resource type is only met by a registration for every resource type.
            string allowed = string.Concat(letters.Where(letter => type == "*" ? registered._byType.TryGetValue("*", out HashSet<char>? any) && any.Contains(letter) : registered.Allows(type, letter)));
            if (allowed.Length > 0) { granted.Add(type, allowed); }
        }
        return granted;
    }

    private void Add(string type, string letters)
    {
        if (!_byType.TryGetValue(type, out HashSet<char>? existing)) { _byType[type] = existing = []; }
        existing.UnionWith(letters);
    }

    public override string ToString() => string.Join(' ', _byType.Select(pair => $"system/{pair.Key}.{string.Concat(Letters.Where(pair.Value.Contains))}"));
}
