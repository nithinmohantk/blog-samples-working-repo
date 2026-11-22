using System.Buffers.Text;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace Desk.Core;

/// <summary>
/// Stands in for the identity provider's token endpoint. The web host uses it to get a short-lived token
/// for the signed-in person, addressed to the agent service. In a real deployment this is a token
/// exchange or on-behalf-of request to the identity provider, signed with a key this code never sees.
/// </summary>
public sealed class LabTokenIssuer(string key, TimeSpan lifetime, TimeProvider? clock = null)
{
    /// <summary>A fake key for the lab. It is in a public repository: it protects nothing.</summary>
    public const string FakeKey = "lab-only-fake-signing-key-not-a-secret-0123456789";
    public const string Issuer = "desk-bff";
    public const string Audience = "desk-agent";

    public string Issue(string subject, string name, IEnumerable<string> roles, string audience = Audience, DateTimeOffset? issuedAt = null)
    {
        DateTimeOffset now = issuedAt ?? (clock ?? TimeProvider.System).GetUtcNow();
        byte[] payload = JsonSerializer.SerializeToUtf8Bytes(new Dictionary<string, object>
        {
            ["iss"] = Issuer,
            ["aud"] = audience,
            ["sub"] = subject,
            ["name"] = name,
            ["roles"] = roles.ToArray(),
            ["iat"] = now.ToUnixTimeSeconds(),
            ["nbf"] = now.ToUnixTimeSeconds(),
            ["exp"] = (now + lifetime).ToUnixTimeSeconds(),
            ["jti"] = Guid.NewGuid().ToString("N"),
        });
        string signingInput = Base64Url.EncodeToString("{\"alg\":\"HS256\",\"typ\":\"JWT\"}"u8) + "." + Base64Url.EncodeToString(payload);
        byte[] signature = HMACSHA256.HashData(Encoding.UTF8.GetBytes(key), Encoding.ASCII.GetBytes(signingInput));
        return signingInput + "." + Base64Url.EncodeToString(signature);
    }
}
