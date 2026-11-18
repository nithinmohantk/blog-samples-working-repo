using System.Collections.Concurrent;
using System.Net.Http.Headers;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;

namespace Smart.Backend.Server;

/// <summary>What was agreed with a client out of band: who it is, where its public keys are, and the most it may ask for.</summary>
public sealed record ClientRegistration
{
    public required string ClientId { get; init; }
    /// <summary>A URL the client controls that serves its JWK Set. Preferred: the client rotates keys by changing what it serves.</summary>
    public Uri? JwksUri { get; init; }
    /// <summary>A JWK Set given at registration. Only for clients that cannot host a URL; rotation then needs a new registration.</summary>
    public JsonObject? Jwks { get; init; }
    public required string Scope { get; init; }
    public TimeSpan AccessTokenLifetime { get; init; } = TimeSpan.FromSeconds(300);
}

public sealed record TokenResult(int Status, JsonObject Body);

/// <summary>One line per decision, for the audit trail. The reason stays on the server; the caller is told much less.</summary>
public sealed record AuditEvent(DateTimeOffset At, string Area, string ClientId, string Decision, string Detail);

/// <summary>Fetches and caches client JWK Sets, for as long as the client's Cache-Control allows and never longer than a ceiling.</summary>
public sealed class JwksResolver(HttpClient http, TimeProvider clock)
{
    private static readonly TimeSpan DefaultLifetime = TimeSpan.FromMinutes(5), Ceiling = TimeSpan.FromHours(1), MinimumBetweenRefreshes = TimeSpan.FromSeconds(10);
    private readonly ConcurrentDictionary<Uri, (JsonObject Jwks, DateTimeOffset FetchedAt, DateTimeOffset FreshUntil)> _cache = new();

    public int Fetches { get; private set; }

    /// <param name="unknownKeyId">True when the cached set did not contain the key ID: the client may have rotated.</param>
    public async Task<JsonObject?> GetAsync(Uri uri, bool unknownKeyId, CancellationToken cancel)
    {
        DateTimeOffset now = clock.GetUtcNow();
        if (_cache.TryGetValue(uri, out var cached))
        {
            // An unknown key ID earns a refetch, but not one per request: that would let anyone make this server hammer the client.
            bool refresh = unknownKeyId ? now - cached.FetchedAt >= MinimumBetweenRefreshes : now >= cached.FreshUntil;
            if (!refresh) { return cached.Jwks; }
        }
        try
        {
            Fetches++;
            using HttpResponseMessage response = await http.GetAsync(uri, cancel);
            if (!response.IsSuccessStatusCode || JsonNode.Parse(await response.Content.ReadAsStringAsync(cancel)) is not JsonObject jwks) { return null; }
            CacheControlHeaderValue? control = response.Headers.CacheControl;
            TimeSpan lifetime = control is { NoStore: true } or { NoCache: true } ? TimeSpan.Zero : control?.MaxAge ?? DefaultLifetime;
            _cache[uri] = (jwks, now, now + (lifetime < Ceiling ? lifetime : Ceiling));
            return jwks;
        }
        catch (Exception error) when (error is HttpRequestException or TaskCanceledException or System.Text.Json.JsonException) { return null; }
    }
}

/// <summary>The token endpoint: authenticates a client by its signed assertion and issues a short-lived access token.</summary>
public sealed class TokenService(
    IReadOnlyDictionary<string, ClientRegistration> clients, JwksResolver jwks, AccessTokens tokens, Uri tokenEndpoint, TimeProvider clock, Action<AuditEvent> audit)
{
    public const string AssertionType = "urn:ietf:params:oauth:client-assertion-type:jwt-bearer";
    private static readonly TimeSpan MaximumAssertionLifetime = TimeSpan.FromMinutes(5), Skew = TimeSpan.FromSeconds(10);
    private readonly ConcurrentDictionary<(string Issuer, string Id), DateTimeOffset> _seen = new();

    public async Task<TokenResult> HandleAsync(IReadOnlyDictionary<string, string> form, CancellationToken cancel)
    {
        string? P(string name) => form.TryGetValue(name, out string? value) && value.Length > 0 ? value : null;
        if (P("grant_type") != "client_credentials") { return Refuse(400, "unsupported_grant_type", "?", "grant_type is not client_credentials"); }
        if (P("client_assertion_type") != AssertionType || P("client_assertion") is not string assertion) { return Refuse(400, "invalid_request", "?", "client assertion missing or of the wrong type"); }

        (ClientRegistration? client, string claimed, string? failure) = await AuthenticateAsync(assertion, cancel);
        // Every authentication failure looks the same from outside. Which check failed is for the audit log only.
        if (client is null) { return Refuse(401, "invalid_client", claimed, failure!); }

        if (ScopeSet.Parse(P("scope")) is not ScopeSet requested || requested.IsEmpty) { return Refuse(400, "invalid_scope", client.ClientId, $"'{P("scope")}' is not a list of SMART v2 system scopes"); }
        ScopeSet granted = requested.GrantFrom(ScopeSet.Parse(client.Scope)!);
        if (granted.IsEmpty) { return Refuse(400, "invalid_scope", client.ClientId, $"nothing in '{requested}' is within the registered '{client.Scope}'"); }

        string token = tokens.Issue(client.ClientId, granted.ToString(), client.AccessTokenLifetime);
        audit(new AuditEvent(clock.GetUtcNow(), "token", client.ClientId, "issued", $"asked '{requested}', granted '{granted}'"));
        return new TokenResult(200, new JsonObject
        {
            ["access_token"] = token, ["token_type"] = "bearer", ["expires_in"] = (int)client.AccessTokenLifetime.TotalSeconds, ["scope"] = granted.ToString(),
        });
    }

    private async Task<(ClientRegistration? Client, string Claimed, string? Failure)> AuthenticateAsync(string assertion, CancellationToken cancel)
    {
        if (Jose.Parse(assertion) is not ParsedJws jws) { return (null, "?", "the assertion is not a compact JWS"); }
        string issuer = jws.ClaimString("iss") ?? "?";

        // The algorithm comes from a fixed list, never from trust in the header.
        string? algorithm = jws.HeaderString("alg");
        if (algorithm is not (Jose.RS384 or Jose.ES384)) { return (null, issuer, $"alg '{algorithm}' is not RS384 or ES384"); }
        if (jws.HeaderString("typ") != "JWT") { return (null, issuer, "typ is not JWT"); }
        if (jws.HeaderString("kid") is not string keyId) { return (null, issuer, "no kid in the header"); }

        if (issuer != jws.ClaimString("sub")) { return (null, issuer, "iss and sub differ"); }
        if (!clients.TryGetValue(issuer, out ClientRegistration? client)) { return (null, issuer, "unknown client"); }
        if (jws.HeaderString("jku") is string jku && jku != client.JwksUri?.ToString()) { return (null, issuer, "jku is not the registered JWK Set URL"); }

        // Exactly one key with this ID and of the type the algorithm needs. The key set is the registered one: the token cannot bring its own.
        AsymmetricAlgorithm? key = await FindKeyAsync(client, keyId, algorithm, refresh: false, cancel) ?? await FindKeyAsync(client, keyId, algorithm, refresh: true, cancel);
        if (key is null) { return (null, issuer, $"no single {algorithm} key with kid '{keyId}' in the registered key set"); }
        using (key)
        {
            if (!Jose.Verify(key, algorithm, jws.SigningInput, jws.Signature)) { return (null, issuer, "the signature does not verify"); }
        }

        DateTimeOffset now = clock.GetUtcNow();
        if (!jws.Audiences.Contains(tokenEndpoint.ToString())) { return (null, issuer, "aud is not this token endpoint"); }
        if (jws.ClaimNumber("exp") is not long seconds) { return (null, issuer, "no exp"); }
        DateTimeOffset expires = DateTimeOffset.FromUnixTimeSeconds(seconds);
        if (expires <= now - Skew) { return (null, issuer, "the assertion has expired"); }
        if (expires > now + MaximumAssertionLifetime + Skew) { return (null, issuer, "exp is more than five minutes away"); }
        if (jws.ClaimNumber("nbf") is long notBefore && DateTimeOffset.FromUnixTimeSeconds(notBefore) > now + Skew) { return (null, issuer, "the assertion is not valid yet"); }

        // One use only. The entry is kept until the assertion could no longer be accepted anyway.
        if (jws.ClaimString("jti") is not { Length: > 0 and <= 128 } id) { return (null, issuer, "no usable jti"); }
        foreach ((var entry, DateTimeOffset until) in _seen) { if (until < now) { _seen.TryRemove(entry, out _); } }
        if (!_seen.TryAdd((issuer, id), expires + Skew)) { return (null, issuer, "this assertion was used before"); }

        return (client, issuer, null);
    }

    private async Task<AsymmetricAlgorithm?> FindKeyAsync(ClientRegistration client, string keyId, string algorithm, bool refresh, CancellationToken cancel)
    {
        if (refresh && client.JwksUri is null) { return null; }
        JsonObject? set = client.JwksUri is Uri uri ? await jwks.GetAsync(uri, refresh, cancel) : client.Jwks;
        List<JsonObject> matches = [.. (set?["keys"] as JsonArray ?? []).OfType<JsonObject>().Where(k =>
            k["kid"] is JsonValue id && id.TryGetValue(out string? text) && text == keyId
            && k["kty"] is JsonValue type && type.TryGetValue(out string? kty) && kty == (algorithm == Jose.RS384 ? "RSA" : "EC"))];
        return matches.Count == 1 ? Jose.ImportPublicJwk(matches[0]) : null;
    }

    private TokenResult Refuse(int status, string error, string clientId, string reason)
    {
        audit(new AuditEvent(clock.GetUtcNow(), "token", clientId, "refused", $"{error}: {reason}"));
        JsonObject body = new() { ["error"] = error };
        if (error != "invalid_client") { body["error_description"] = reason; }
        return new TokenResult(status, body);
    }
}

/// <summary>Issues and checks this server's own access tokens: a JWT signed with ES384, valid for one FHIR base URL.</summary>
public sealed class AccessTokens(ECDsa signingKey, Uri issuer, Uri audience, TimeProvider clock)
{
    private readonly string _keyId = Jose.PublicJwk(signingKey)["kid"]!.GetValue<string>();

    public JsonObject Jwks => new() { ["keys"] = new JsonArray(Jose.PublicJwk(signingKey)) };

    public string Issue(string clientId, string scope, TimeSpan lifetime)
    {
        DateTimeOffset now = clock.GetUtcNow();
        JsonObject header = new() { ["alg"] = Jose.ES384, ["kid"] = _keyId, ["typ"] = "at+jwt" };
        JsonObject claims = new()
        {
            ["iss"] = issuer.ToString(), ["aud"] = audience.ToString(), ["sub"] = clientId, ["client_id"] = clientId, ["scope"] = scope,
            ["iat"] = now.ToUnixTimeSeconds(), ["exp"] = now.Add(lifetime).ToUnixTimeSeconds(), ["jti"] = Guid.NewGuid().ToString("N"),
        };
        string input = Jose.SigningInput(header, claims);
        return Jose.Compact(input, Jose.Sign(signingKey, Encoding.ASCII.GetBytes(input)));
    }

    /// <summary>Returns the client and its scopes, or the reason the token is not acceptable.</summary>
    public (string ClientId, ScopeSet Scopes, string Raw)? Validate(string? token, out string failure)
    {
        failure = "";
        if (Jose.Parse(token) is not ParsedJws jws) { failure = "not a JWT"; return null; }
        if (jws.HeaderString("alg") != Jose.ES384 || jws.HeaderString("kid") != _keyId || jws.HeaderString("typ") != "at+jwt") { failure = "not an access token from this server"; return null; }
        if (!Jose.Verify(signingKey, Jose.ES384, jws.SigningInput, jws.Signature)) { failure = "the signature does not verify"; return null; }
        if (jws.ClaimString("iss") != issuer.ToString() || !jws.Audiences.Contains(audience.ToString())) { failure = "issued by or for another server"; return null; }
        if (jws.ClaimNumber("exp") is not long seconds || DateTimeOffset.FromUnixTimeSeconds(seconds) <= clock.GetUtcNow()) { failure = "expired"; return null; }
        if (jws.ClaimString("client_id") is not string clientId || ScopeSet.Parse(jws.ClaimString("scope")) is not ScopeSet scopes) { failure = "no client or scope"; return null; }
        return (clientId, scopes, jws.ClaimString("scope")!);
    }
}
