using System.Net.Http.Headers;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;

namespace Smart.Backend;

/// <summary>
/// Signs the client assertion. The interface exists so that the private key never has to be in this process:
/// a key vault, a cloud KMS or an HSM signs the bytes it is given and returns the signature.
/// </summary>
public interface IAssertionSigner
{
    string Algorithm { get; }
    string KeyId { get; }
    ValueTask<byte[]> SignAsync(ReadOnlyMemory<byte> data, CancellationToken cancel);
}

/// <summary>A signer for a key held in memory. Right for tests and development; in production prefer a remote signer.</summary>
public sealed class LocalKeySigner(AsymmetricAlgorithm key) : IAssertionSigner
{
    public string Algorithm { get; } = Jose.AlgorithmFor(key);
    public string KeyId { get; } = Jose.PublicJwk(key)["kid"]!.GetValue<string>();
    public ValueTask<byte[]> SignAsync(ReadOnlyMemory<byte> data, CancellationToken cancel) => ValueTask.FromResult(Jose.Sign(key, data.Span));
}

public sealed record SmartClientOptions
{
    /// <summary>The FHIR base URL, ending in a slash. Discovery and every FHIR call are relative to it.</summary>
    public required Uri FhirBase { get; init; }
    public required string ClientId { get; init; }
    /// <summary>What to ask for, for example "system/Patient.rs system/Observation.rs".</summary>
    public required string Scope { get; init; }
    /// <summary>If true, a token that grants less than was asked for is an error instead of a surprise later.</summary>
    public bool RequireAllScopes { get; init; } = true;
    /// <summary>How long the assertion is valid. The specification allows at most five minutes.</summary>
    public TimeSpan AssertionLifetime { get; init; } = TimeSpan.FromMinutes(2);
    /// <summary>A token this close to expiry is replaced before it is used.</summary>
    public TimeSpan RefreshBefore { get; init; } = TimeSpan.FromSeconds(30);
}

public sealed record AccessToken(string Value, DateTimeOffset ExpiresAt, string Scope);

public sealed class SmartTokenException(string error, string? description, int status) : Exception($"{error}{(description is null ? "" : $": {description}")} (HTTP {status})")
{
    public string Error { get; } = error;
    public int Status { get; } = status;
}

/// <summary>SMART Backend Services from the client's side: discovery, a signed assertion, and a cached access token.</summary>
public sealed class SmartBackendClient(HttpClient http, SmartClientOptions options, IAssertionSigner signer, TimeProvider clock)
{
    private readonly SemaphoreSlim _gate = new(1, 1);
    private Uri? _tokenEndpoint;
    private AccessToken? _token;

    /// <summary>How many times the token endpoint was called. Useful in a test and as a metric.</summary>
    public int TokenRequests { get; private set; }

    public SmartClientOptions Options => options;

    public async Task<AccessToken> GetTokenAsync(CancellationToken cancel = default)
    {
        if (Usable(_token)) { return _token!; }
        // One caller fetches; the rest wait and then find the token in the cache.
        await _gate.WaitAsync(cancel);
        try
        {
            if (Usable(_token)) { return _token!; }
            _tokenEndpoint ??= await DiscoverAsync(cancel);
            _token = await RequestTokenAsync(_tokenEndpoint, await BuildAssertionAsync(_tokenEndpoint, cancel), cancel);
            return _token;
        }
        finally { _gate.Release(); }
    }

    /// <summary>Forgets the cached token, for example after the server answered 401 to it.</summary>
    public void Invalidate(AccessToken rejected) => Interlocked.CompareExchange(ref _token, null, rejected);

    private bool Usable(AccessToken? token) => token is not null && token.ExpiresAt - options.RefreshBefore > clock.GetUtcNow();

    public async Task<Uri> DiscoverAsync(CancellationToken cancel = default)
    {
        RequireSecure(options.FhirBase, "FHIR base URL");
        using HttpResponseMessage response = await http.GetAsync(new Uri(options.FhirBase, ".well-known/smart-configuration"), cancel);
        response.EnsureSuccessStatusCode();
        JsonObject configuration = JsonNode.Parse(await response.Content.ReadAsStringAsync(cancel))!.AsObject();
        bool Lists(string name, string value) => configuration[name] is JsonArray values && values.Any(v => v?.GetValue<string>() == value);
        if (!Lists("grant_types_supported", "client_credentials") || !Lists("capabilities", "client-confidential-asymmetric"))
        {
            throw new InvalidOperationException("This server does not advertise SMART Backend Services (client_credentials with client-confidential-asymmetric).");
        }
        if (configuration["token_endpoint_auth_signing_alg_values_supported"] is JsonArray algorithms && !algorithms.Any(a => a?.GetValue<string>() == signer.Algorithm))
        {
            throw new InvalidOperationException($"This server does not accept {signer.Algorithm} client assertions.");
        }
        Uri endpoint = new(configuration["token_endpoint"]!.GetValue<string>());
        RequireSecure(endpoint, "token endpoint");
        return endpoint;
    }

    /// <summary>The one-time JWT that proves who is asking. Public so a test can build one and tamper with it.</summary>
    public async Task<string> BuildAssertionAsync(Uri tokenEndpoint, CancellationToken cancel = default)
    {
        DateTimeOffset now = clock.GetUtcNow();
        JsonObject header = new() { ["alg"] = signer.Algorithm, ["kid"] = signer.KeyId, ["typ"] = "JWT" };
        JsonObject claims = new()
        {
            ["iss"] = options.ClientId,
            ["sub"] = options.ClientId,
            ["aud"] = tokenEndpoint.ToString(),
            ["exp"] = now.Add(options.AssertionLifetime).ToUnixTimeSeconds(),
            ["jti"] = Guid.NewGuid().ToString("N"),
        };
        string input = Jose.SigningInput(header, claims);
        return Jose.Compact(input, await signer.SignAsync(Encoding.ASCII.GetBytes(input), cancel));
    }

    public async Task<AccessToken> RequestTokenAsync(Uri tokenEndpoint, string assertion, CancellationToken cancel = default)
    {
        using FormUrlEncodedContent form = new(new Dictionary<string, string>
        {
            ["grant_type"] = "client_credentials",
            ["scope"] = options.Scope,
            ["client_assertion_type"] = "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
            ["client_assertion"] = assertion,
        });
        DateTimeOffset asked = clock.GetUtcNow();
        TokenRequests++;
        using HttpResponseMessage response = await http.PostAsync(tokenEndpoint, form, cancel);
        JsonObject body = JsonNode.Parse(await response.Content.ReadAsStringAsync(cancel)) as JsonObject ?? [];
        if (!response.IsSuccessStatusCode)
        {
            throw new SmartTokenException(body["error"]?.GetValue<string>() ?? "token_request_failed", body["error_description"]?.GetValue<string>(), (int)response.StatusCode);
        }
        if (!string.Equals(body["token_type"]?.GetValue<string>(), "bearer", StringComparison.OrdinalIgnoreCase))
        {
            throw new InvalidOperationException("The token endpoint did not return a bearer token.");
        }
        // The server may grant less than was asked for. Find out now, not at the first 403.
        string granted = body["scope"]?.GetValue<string>() ?? "";
        string[] missing = [.. options.Scope.Split(' ', StringSplitOptions.RemoveEmptyEntries).Except(granted.Split(' ', StringSplitOptions.RemoveEmptyEntries))];
        if (options.RequireAllScopes && missing.Length > 0)
        {
            throw new SmartTokenException("insufficient_scope", $"asked for '{options.Scope}', granted '{granted}'", (int)response.StatusCode);
        }
        return new AccessToken(body["access_token"]!.GetValue<string>(), asked.AddSeconds(body["expires_in"]!.GetValue<int>()), granted);
    }

    private static void RequireSecure(Uri uri, string what)
    {
        if (uri.Scheme != Uri.UriSchemeHttps && !uri.IsLoopback) { throw new InvalidOperationException($"The {what} must use https: {uri}"); }
    }
}

/// <summary>
/// Puts the access token on requests to the FHIR server and nowhere else. A FHIR resource can contain a
/// reference to any URL; following one must not hand this server's token to another host.
/// </summary>
public sealed class SmartBackendHandler(SmartBackendClient client) : DelegatingHandler(new SocketsHttpHandler { AllowAutoRedirect = false })
{
    protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancel)
    {
        Uri fhir = client.Options.FhirBase;
        // "Ours" is the FHIR base and everything under it. A server writes its paging links as [base]?_getpages=..., without the slash.
        bool ours = request.RequestUri is Uri uri && uri.Scheme == fhir.Scheme && uri.Authority == fhir.Authority && $"{uri.AbsolutePath}/".StartsWith(fhir.AbsolutePath, StringComparison.Ordinal);
        if (!ours) { return await base.SendAsync(request, cancel); }

        if (request.Content is not null) { await request.Content.LoadIntoBufferAsync(cancel); }      // so the request can be sent twice
        AccessToken token = await client.GetTokenAsync(cancel);
        request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", token.Value);
        HttpResponseMessage response = await base.SendAsync(request, cancel);
        if (response.StatusCode != System.Net.HttpStatusCode.Unauthorized) { return response; }

        // The token was refused: expired early, revoked, or the server restarted with new keys. Get one new token and try once.
        response.Dispose();
        client.Invalidate(token);
        token = await client.GetTokenAsync(cancel);
        request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", token.Value);
        return await base.SendAsync(request, cancel);
    }
}
