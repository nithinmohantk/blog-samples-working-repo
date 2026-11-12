using System.Security.Claims;
using System.Text.Encodings.Web;
using System.Text.Json.Nodes;
using Microsoft.AspNetCore.Authentication;
using Microsoft.Extensions.Options;

namespace FhirFacade.SelfTest;

/// <summary>
/// Test-only authentication: the claims arrive as JSON in the X-Test-Claims header. It replaces JWT validation
/// so the self-test needs no package. It must never be registered in a deployed host.
/// </summary>
public sealed class TestAuthHandler(
    IOptionsMonitor<AuthenticationSchemeOptions> options, ILoggerFactory logger, UrlEncoder encoder)
    : AuthenticationHandler<AuthenticationSchemeOptions>(options, logger, encoder)
{
    public const string SchemeName = "Test";
    public const string Header = "X-Test-Claims";

    protected override Task<AuthenticateResult> HandleAuthenticateAsync()
    {
        if (!Request.Headers.TryGetValue(Header, out var header))
        {
            return Task.FromResult(AuthenticateResult.NoResult());
        }

        List<Claim> claims = [];
        foreach ((string name, JsonNode? value) in JsonNode.Parse(header.ToString())!.AsObject())
        {
            // A JSON array becomes one claim per element, which is what the JWT handler does with "roles".
            JsonNode?[] values = value is JsonArray array ? [.. array] : [value];
            claims.AddRange(values.Select(v => new Claim(name, (string)v!)));
        }

        ClaimsPrincipal principal = new(new ClaimsIdentity(claims, SchemeName));
        return Task.FromResult(AuthenticateResult.Success(new AuthenticationTicket(principal, SchemeName)));
    }
}
