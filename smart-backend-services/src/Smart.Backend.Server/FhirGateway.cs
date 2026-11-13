using System.Buffers.Text;
using System.Net.Http.Headers;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Routing;

namespace Smart.Backend.Server;

/// <summary>
/// Sits in front of a FHIR server that has no idea about SMART. It checks the access token, works out what the
/// request needs, compares that with what the token grants, and only then forwards the request. The FHIR server
/// behind it must not be reachable any other way.
/// </summary>
public sealed class FhirGateway(HttpClient upstream, Uri upstreamBase, Uri publicFhirBase, Uri tokenEndpoint, AccessTokens tokens, TimeProvider clock, Action<AuditEvent> audit)
{
    private static readonly string[] ForwardedRequestHeaders = ["Accept", "If-Match", "If-None-Match", "If-Modified-Since", "Prefer"];
    private static readonly string[] ReturnedResponseHeaders = ["ETag", "Last-Modified", "Location", "Content-Location"];
    private readonly byte[] _pageKey = RandomNumberGenerator.GetBytes(48);

    public JsonObject SmartConfiguration => new()
    {
        ["token_endpoint"] = tokenEndpoint.ToString(),
        ["grant_types_supported"] = new JsonArray("client_credentials"),
        ["token_endpoint_auth_methods_supported"] = new JsonArray("private_key_jwt"),
        ["token_endpoint_auth_signing_alg_values_supported"] = new JsonArray(Jose.RS384, Jose.ES384),
        ["scopes_supported"] = new JsonArray("system/*.cruds", "system/Patient.rs", "system/Observation.rs"),
        ["capabilities"] = new JsonArray("client-confidential-asymmetric", "permission-v2"),
        ["code_challenge_methods_supported"] = new JsonArray("S256"),
    };

    public async Task HandleAsync(HttpContext http)
    {
        HttpRequest request = http.Request;
        string path = (http.GetRouteValue("path") as string ?? "").Trim('/');
        string method = request.Method.ToUpperInvariant();

        // Two things are public by specification: discovery and the capability statement.
        if (method == "GET" && path == ".well-known/smart-configuration") { await WriteAsync(http, 200, SmartConfiguration, "application/json"); return; }
        if (method == "GET" && path == "metadata") { await ForwardAsync(http, method, "metadata", null, null); return; }

        string? bearer = request.Headers.Authorization.ToString() is { } header && header.StartsWith("Bearer ", StringComparison.OrdinalIgnoreCase) ? header[7..].Trim() : null;
        if (tokens.Validate(bearer, out string failure) is not (string clientId, ScopeSet scopes, string rawScope))
        {
            audit(new AuditEvent(clock.GetUtcNow(), "fhir", "?", "401", $"{method} {path}: {(bearer is null ? "no bearer token" : failure)}"));
            http.Response.Headers.WWWAuthenticate = bearer is null ? "Bearer" : "Bearer error=\"invalid_token\"";
            await WriteAsync(http, 401, Outcome("login", "A valid access token is required."));
            return;
        }

        List<KeyValuePair<string, string>> query = FhirRequestClassifier.ParseQuery(request.QueryString.Value ?? "");
        byte[]? body = null;
        if (request.ContentLength > 0 || request.Headers.TransferEncoding.Count > 0)
        {
            using MemoryStream buffer = new();
            await request.Body.CopyToAsync(buffer, http.RequestAborted);
            body = buffer.ToArray();
        }

        // A next-page link is only good for the client, and the scopes, that ran the search it belongs to.
        if (method == "GET" && path.Length == 0 && query.FirstOrDefault(p => p.Key == "_getpages").Value is { Length: > 0 } pageId)
        {
            byte[] presented = Encoding.ASCII.GetBytes(query.FirstOrDefault(p => p.Key == "_pt").Value ?? ""), expected = Encoding.ASCII.GetBytes(PageToken(clientId, rawScope, pageId));
            if (!CryptographicOperations.FixedTimeEquals(presented, expected))
            {
                await DenyAsync(http, clientId, $"{method} ?_getpages", "this page link was not issued to this client with these scopes", null);
                return;
            }
            string paging = string.Join('&', query.Where(p => p.Key != "_pt").Select(p => $"{Uri.EscapeDataString(p.Key)}={Uri.EscapeDataString(p.Value)}"));
            audit(new AuditEvent(clock.GetUtcNow(), "fhir", clientId, "allowed", "GET ?_getpages"));
            await ForwardAsync(http, method, $"?{paging}", null, (clientId, rawScope));
            return;
        }

        JsonObject? json = null;
        if (body is not null && path.Length == 0)
        {
            try { json = JsonNode.Parse(body) as JsonObject; }
            catch (System.Text.Json.JsonException) { json = null; }
        }
        Classification needed = FhirRequestClassifier.Classify(method, path, query, json);
        string shape = $"{method} {path}{(query.Count > 0 ? "?" + string.Join('&', query.Select(p => p.Key)) : "")}";      // parameter names only: values can identify a patient
        if (needed.Refusal is not null) { await DenyAsync(http, clientId, shape, needed.Refusal, null); return; }
        Need[] missing = [.. needed.Needs.Where(need => !scopes.Allows(need.Type, need.Letter))];
        if (missing.Length > 0) { await DenyAsync(http, clientId, shape, $"the token does not grant {string.Join(", ", missing)}", string.Join(' ', missing)); return; }

        audit(new AuditEvent(clock.GetUtcNow(), "fhir", clientId, "allowed", $"{shape} needs {string.Join(' ', needed.Needs)}"));
        await ForwardAsync(http, method, path + request.QueryString.Value, body, (clientId, rawScope));
    }

    private async Task DenyAsync(HttpContext http, string clientId, string shape, string reason, string? scope)
    {
        audit(new AuditEvent(clock.GetUtcNow(), "fhir", clientId, "403", $"{shape}: {reason}"));
        http.Response.Headers.WWWAuthenticate = scope is null ? "Bearer error=\"insufficient_scope\"" : $"Bearer error=\"insufficient_scope\", scope=\"{scope}\"";
        await WriteAsync(http, 403, Outcome("forbidden", reason));
    }

    private async Task ForwardAsync(HttpContext http, string method, string relative, byte[]? body, (string ClientId, string Scope)? caller)
    {
        // The base itself, for a transaction or a paging link, is addressed without a trailing slash.
        Uri target = relative.Length == 0 || relative[0] == '?' ? new Uri(upstreamBase.ToString().TrimEnd('/') + relative) : new Uri(upstreamBase, relative);
        using HttpRequestMessage outgoing = new(new HttpMethod(method), target);
        // The caller's token stops here. Only headers that mean something to a FHIR server go on.
        foreach (string name in ForwardedRequestHeaders)
        {
            if (http.Request.Headers.TryGetValue(name, out var values)) { outgoing.Headers.TryAddWithoutValidation(name, values.ToArray()); }
        }
        if (body is not null)
        {
            outgoing.Content = new ByteArrayContent(body);
            outgoing.Content.Headers.ContentType = MediaTypeHeaderValue.Parse(http.Request.ContentType ?? "application/fhir+json");
        }
        using HttpResponseMessage response = await upstream.SendAsync(outgoing, http.RequestAborted);
        string text = await response.Content.ReadAsStringAsync(http.RequestAborted);

        // The FHIR server describes itself by its internal address. Callers must only ever see the public one.
        string inside = upstreamBase.ToString().TrimEnd('/'), outside = publicFhirBase.ToString().TrimEnd('/');
        text = text.Replace(inside, outside, StringComparison.Ordinal);
        if (caller is var (clientId, scope) && text.Contains("_getpages=", StringComparison.Ordinal) && JsonNode.Parse(text) is JsonObject bundle && bundle["link"] is JsonArray links)
        {
            foreach (JsonNode? link in links)
            {
                if (link?["url"]?.GetValue<string>() is string url && FhirRequestClassifier.ParseQuery(new Uri(url).Query).FirstOrDefault(p => p.Key == "_getpages").Value is { Length: > 0 } pageId)
                {
                    link["url"] = $"{url}&_pt={PageToken(clientId, scope, pageId)}";
                }
            }
            text = bundle.ToJsonString();
        }
        foreach (string name in ReturnedResponseHeaders)
        {
            if (response.Headers.TryGetValues(name, out var values) || response.Content.Headers.TryGetValues(name, out values))
            {
                http.Response.Headers[name] = values.Select(v => v.Replace(inside, outside, StringComparison.Ordinal)).ToArray();
            }
        }
        http.Response.StatusCode = (int)response.StatusCode;
        http.Response.ContentType = response.Content.Headers.ContentType?.ToString() ?? "application/fhir+json";
        await http.Response.WriteAsync(text, http.RequestAborted);
    }

    private string PageToken(string clientId, string scope, string pageId) =>
        Base64Url.EncodeToString(HMACSHA384.HashData(_pageKey, Encoding.UTF8.GetBytes($"{clientId}\n{scope}\n{pageId}")).AsSpan(0, 24));

    private static JsonObject Outcome(string code, string text) => new()
    {
        ["resourceType"] = "OperationOutcome",
        ["issue"] = new JsonArray(new JsonObject { ["severity"] = "error", ["code"] = code, ["diagnostics"] = text }),
    };

    private static async Task WriteAsync(HttpContext http, int status, JsonObject body, string contentType = "application/fhir+json")
    {
        http.Response.StatusCode = status;
        http.Response.ContentType = contentType;
        await http.Response.WriteAsync(body.ToJsonString(), http.RequestAborted);
    }
}
