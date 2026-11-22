using System.Security.Claims;
using Microsoft.AspNetCore.Authentication.Cookies;

namespace Desk.Bff;

/// <summary>Marks this assembly for the tests that start the web host in memory.</summary>
public sealed class BffService;

/// <summary>
/// Two invented people, standing in for a directory. The sign-in page that uses them stands in for an
/// OpenID Connect sign-in: replace both with AddOpenIdConnect and the cookie setup stays as it is.
/// </summary>
public static class LabUsers
{
    private static readonly Dictionary<string, (string Name, string Role)> s_users = new(StringComparer.Ordinal)
    {
        ["sam"] = ("Sam (order desk)", "agent"),
        ["alex"] = ("Alex (supervisor)", "supervisor"),
    };

    public static ClaimsPrincipal? Find(string? id)
        => id is not null && s_users.TryGetValue(id, out var user)
            ? new ClaimsPrincipal(new ClaimsIdentity(
                [new Claim("sub", id), new Claim("name", user.Name), new Claim("roles", user.Role)],
                CookieAuthenticationDefaults.AuthenticationScheme, "name", "roles"))
            : null;

    public const string SignInPage = """
        <!DOCTYPE html>
        <html lang="en"><head><meta charset="utf-8" /><title>Sign in</title>
        <style>body{font-family:system-ui,sans-serif;background:#f6f8fa;color:#1f2328;display:grid;place-items:center;height:100vh;margin:0}
        main{background:#fff;border:1px solid #d0d7de;border-radius:8px;padding:24px 32px;max-width:420px}
        button{font:inherit;padding:8px 16px;margin:6px 8px 0 0;border:1px solid #0969da;background:#0969da;color:#fff;border-radius:6px;cursor:pointer}
        p{color:#57606a;font-size:14px}</style></head>
        <body><main><h1>Order desk</h1>
        <p>Lab sign-in. It stands in for the organisation's identity provider and asks for no password.</p>
        <form method="post" action="/signin">
          <button name="user" value="sam">Sign in as Sam (order desk)</button>
          <button name="user" value="alex">Sign in as Alex (supervisor)</button>
        </form></main></body></html>
        """;
}
