using System.Buffers.Text;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace Smart.Backend;

/// <summary>
/// The two signature algorithms SMART names for asymmetric client authentication, and nothing else. There is
/// no "none" and no HMAC here on purpose: a verifier that accepts whatever the token header asks for can be
/// talked into checking an RSA public key as if it were a shared secret.
/// </summary>
public static class Jose
{
    public const string RS384 = "RS384", ES384 = "ES384";

    public static string AlgorithmFor(AsymmetricAlgorithm key) => key switch
    {
        ECDsa => ES384,
        RSA => RS384,
        _ => throw new NotSupportedException("Only RSA and ECDSA keys are supported."),
    };

    public static byte[] Sign(AsymmetricAlgorithm key, ReadOnlySpan<byte> data) => key switch
    {
        // JWS wants the fixed-width r||s form for ECDSA, not the DER form certificates use.
        ECDsa ec => ec.SignData(data, HashAlgorithmName.SHA384, DSASignatureFormat.IeeeP1363FixedFieldConcatenation),
        RSA rsa => rsa.SignData(data, HashAlgorithmName.SHA384, RSASignaturePadding.Pkcs1),
        _ => throw new NotSupportedException("Only RSA and ECDSA keys are supported."),
    };

    public static bool Verify(AsymmetricAlgorithm key, string algorithm, ReadOnlySpan<byte> data, ReadOnlySpan<byte> signature) => (key, algorithm) switch
    {
        (ECDsa ec, ES384) => ec.VerifyData(data, signature, HashAlgorithmName.SHA384, DSASignatureFormat.IeeeP1363FixedFieldConcatenation),
        (RSA rsa, RS384) => rsa.VerifyData(data, signature, HashAlgorithmName.SHA384, RSASignaturePadding.Pkcs1),
        _ => false,       // the key type and the algorithm in the header disagree
    };

    /// <summary>header.payload, ready to be signed.</summary>
    public static string SigningInput(JsonObject header, JsonObject payload) =>
        $"{Base64Url.EncodeToString(Encoding.UTF8.GetBytes(header.ToJsonString()))}.{Base64Url.EncodeToString(Encoding.UTF8.GetBytes(payload.ToJsonString()))}";

    public static string Compact(string signingInput, ReadOnlySpan<byte> signature) => $"{signingInput}.{Base64Url.EncodeToString(signature)}";

    /// <summary>Splits a compact JWS. Returns null for anything that is not three base64url parts with JSON objects in the first two.</summary>
    public static ParsedJws? Parse(string? token)
    {
        if (string.IsNullOrEmpty(token) || token.Length > 8192) { return null; }
        string[] parts = token.Split('.');
        if (parts.Length != 3) { return null; }
        try
        {
            if (JsonNode.Parse(Base64Url.DecodeFromChars(parts[0])) is not JsonObject header || JsonNode.Parse(Base64Url.DecodeFromChars(parts[1])) is not JsonObject payload) { return null; }
            return new ParsedJws(header, payload, Encoding.ASCII.GetBytes($"{parts[0]}.{parts[1]}"), Base64Url.DecodeFromChars(parts[2]));
        }
        catch (Exception error) when (error is FormatException or JsonException) { return null; }
    }

    /// <summary>The public half of a key as a JWK, with the RFC 7638 thumbprint as its key ID.</summary>
    public static JsonObject PublicJwk(AsymmetricAlgorithm key)
    {
        JsonObject jwk;
        switch (key)
        {
            case ECDsa ec:
                ECParameters point = ec.ExportParameters(false);
                jwk = new JsonObject { ["kty"] = "EC", ["crv"] = "P-384", ["x"] = Base64Url.EncodeToString(point.Q.X), ["y"] = Base64Url.EncodeToString(point.Q.Y) };
                break;
            case RSA rsa:
                RSAParameters numbers = rsa.ExportParameters(false);
                jwk = new JsonObject { ["kty"] = "RSA", ["n"] = Base64Url.EncodeToString(numbers.Modulus), ["e"] = Base64Url.EncodeToString(numbers.Exponent) };
                break;
            default: throw new NotSupportedException("Only RSA and ECDSA keys are supported.");
        }
        jwk["kid"] = Thumbprint(jwk);
        jwk["alg"] = AlgorithmFor(key);
        jwk["use"] = "sig";
        return jwk;
    }

    /// <summary>RFC 7638: SHA-256 over the required members only, in alphabetical order, with no white space.</summary>
    public static string Thumbprint(JsonObject jwk)
    {
        string S(string name) => jwk[name]!.GetValue<string>();
        string canonical = S("kty") == "EC"
            ? $$"""{"crv":"{{S("crv")}}","kty":"EC","x":"{{S("x")}}","y":"{{S("y")}}"}"""
            : $$"""{"e":"{{S("e")}}","kty":"RSA","n":"{{S("n")}}"}""";
        return Base64Url.EncodeToString(SHA256.HashData(Encoding.UTF8.GetBytes(canonical)));
    }

    /// <summary>Imports a public JWK. Returns null for a key this sample will not verify with: wrong curve, short RSA, bad encoding.</summary>
    public static AsymmetricAlgorithm? ImportPublicJwk(JsonObject jwk)
    {
        try
        {
            string? S(string name) => jwk[name] is JsonValue value && value.TryGetValue(out string? text) ? text : null;
            switch (S("kty"))
            {
                case "EC" when S("crv") == "P-384" && S("x") is string x && S("y") is string y:
                    return ECDsa.Create(new ECParameters { Curve = ECCurve.NamedCurves.nistP384, Q = new ECPoint { X = Base64Url.DecodeFromChars(x), Y = Base64Url.DecodeFromChars(y) } });
                case "RSA" when S("n") is string n && S("e") is string e:
                    RSA rsa = RSA.Create(new RSAParameters { Modulus = Base64Url.DecodeFromChars(n), Exponent = Base64Url.DecodeFromChars(e) });
                    if (rsa.KeySize < 2048) { rsa.Dispose(); return null; }
                    return rsa;
                default: return null;
            }
        }
        catch (Exception error) when (error is FormatException or CryptographicException) { return null; }
    }
}

public sealed record ParsedJws(JsonObject Header, JsonObject Payload, byte[] SigningInput, byte[] Signature)
{
    public string? HeaderString(string name) => Text(Header[name]);
    public string? ClaimString(string name) => Text(Payload[name]);
    public long? ClaimNumber(string name) => Payload[name] is JsonValue value && value.TryGetValue(out long number) ? number : null;

    /// <summary>"aud" may be one string or an array of them.</summary>
    public IReadOnlyList<string> Audiences => Payload["aud"] switch
    {
        JsonArray many => [.. many.Select(Text).OfType<string>()],
        JsonNode one when Text(one) is string text => [text],
        _ => [],
    };

    private static string? Text(JsonNode? node) => node is JsonValue value && value.TryGetValue(out string? text) ? text : null;
}
