using System.Security.Claims;
using System.Text.RegularExpressions;

namespace FhirFacade.Auth;

public sealed record AccessDecision(bool Allowed, string Reason, SmartContext? GrantedBy = null);

/// <summary>Decides whether the caller may perform one interaction on one patient's data.</summary>
public static partial class SmartAccess
{
    // Entra ID puts delegated scopes in "scp" and application permissions in "roles".
    // SMART authorization servers use "scope".
    private static readonly string[] SpaceSeparatedScopeClaims = ["scp", "scope"];
    private static readonly string[] PatientIdentityClaims = ["fhirUser", "extension_fhirUser"];

    [GeneratedRegex(@"(?:^|/)Patient/(?<id>[A-Za-z0-9\-\.]{1,64})$", RegexOptions.CultureInvariant)]
    private static partial Regex PatientReference();

    public static IReadOnlyList<SmartScope> ScopesOf(ClaimsPrincipal user)
    {
        IEnumerable<string> raw = user.Claims
            .Where(claim => SpaceSeparatedScopeClaims.Contains(claim.Type))
            .SelectMany(claim => claim.Value.Split(' ', StringSplitOptions.RemoveEmptyEntries))
            .Concat(user.Claims.Where(claim => claim.Type == "roles").Select(claim => claim.Value));

        List<SmartScope> scopes = [];
        foreach (string value in raw)
        {
            if (SmartScope.TryParse(value, out SmartScope? scope))
            {
                scopes.Add(scope!);
            }
        }

        return scopes;
    }

    /// <summary>The patient the token was issued to, taken from the fhirUser claim. Null for any other kind of user.</summary>
    public static string? PatientOf(ClaimsPrincipal user)
    {
        foreach (string type in PatientIdentityClaims)
        {
            Match match = PatientReference().Match(user.FindFirst(type)?.Value ?? "");
            if (match.Success)
            {
                return match.Groups["id"].Value;
            }
        }

        return null;
    }

    public static AccessDecision Evaluate(
        ClaimsPrincipal user, string resourceType, SmartPermissions needed, string patientId)
    {
        List<SmartScope> covering = [.. ScopesOf(user).Where(scope => scope.Covers(resourceType, needed))];

        if (covering.Any(scope => scope.Context == SmartContext.System))
        {
            return new AccessDecision(true, "system scope", SmartContext.System);
        }

        if (covering.Any(scope => scope.Context == SmartContext.Patient))
        {
            string? tokenPatient = PatientOf(user);
            if (tokenPatient is null)
            {
                return new AccessDecision(false, "patient scope without a fhirUser claim that names a Patient");
            }

            return string.Equals(tokenPatient, patientId, StringComparison.Ordinal)
                ? new AccessDecision(true, "patient scope", SmartContext.Patient)
                : new AccessDecision(false, "the token was issued for a different patient");
        }

        // A user/ scope means "whatever this user may see". Deciding that needs a source of care
        // relationships, which this facade does not have, so it refuses instead of granting every patient.
        return covering.Any(scope => scope.Context == SmartContext.User)
            ? new AccessDecision(false, "user-level scopes are not supported by this server")
            : new AccessDecision(false, "the token carries no scope that allows this interaction");
    }
}
