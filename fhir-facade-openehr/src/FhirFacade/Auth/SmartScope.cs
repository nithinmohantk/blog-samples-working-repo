using System.Text.RegularExpressions;

namespace FhirFacade.Auth;

public enum SmartContext
{
    Patient,
    User,
    System,
}

[Flags]
public enum SmartPermissions
{
    None = 0,
    Create = 1,
    Read = 2,
    Update = 4,
    Delete = 8,
    Search = 16,
    All = Create | Read | Update | Delete | Search,
}

/// <summary>
/// One SMART on FHIR resource scope. Accepts SMART v1 (<c>patient/Observation.read</c>) and v2
/// (<c>patient/Observation.rs</c>), and the spelling Microsoft Entra ID needs because it does not accept a
/// forward slash in a scope name: <c>patient.Observation.rs</c>, with <c>all</c> standing in for <c>*</c>.
/// </summary>
public sealed partial record SmartScope(SmartContext Context, string Resource, SmartPermissions Permissions)
{
    public const string AnyResource = "*";

    // The permission letters of SMART v2 must appear in the order c, r, u, d, s.
    [GeneratedRegex(@"^(?<context>patient|user|system)[/.](?<resource>\*|all|[A-Z][A-Za-z]+)\.(?<permission>\*|all|read|write|c?r?u?d?s?)$",
        RegexOptions.CultureInvariant)]
    private static partial Regex Pattern();

    /// <summary>
    /// Returns false for anything that is not a plain resource scope. That includes SMART v2 scopes with a
    /// query constraint (<c>...rs?category=...</c>): this facade cannot enforce the constraint, so the scope
    /// grants nothing instead of being read as unconstrained.
    /// </summary>
    public static bool TryParse(string value, out SmartScope? scope)
    {
        scope = null;
        Match match = Pattern().Match(value);
        string permission = match.Groups["permission"].Value;
        if (!match.Success || permission.Length == 0)
        {
            return false;
        }

        SmartPermissions permissions = permission switch
        {
            "*" or "all" => SmartPermissions.All,
            "read" => SmartPermissions.Read | SmartPermissions.Search,
            "write" => SmartPermissions.Create | SmartPermissions.Update | SmartPermissions.Delete,
            _ => permission.Aggregate(SmartPermissions.None, (acc, letter) => acc | letter switch
            {
                'c' => SmartPermissions.Create,
                'r' => SmartPermissions.Read,
                'u' => SmartPermissions.Update,
                'd' => SmartPermissions.Delete,
                _ => SmartPermissions.Search,
            }),
        };

        string resource = match.Groups["resource"].Value;
        scope = new SmartScope(
            Enum.Parse<SmartContext>(match.Groups["context"].Value, ignoreCase: true),
            resource is "all" ? AnyResource : resource,
            permissions);
        return true;
    }

    public bool Covers(string resourceType, SmartPermissions needed) =>
        (Resource == AnyResource || Resource == resourceType) && (Permissions & needed) == needed;
}
