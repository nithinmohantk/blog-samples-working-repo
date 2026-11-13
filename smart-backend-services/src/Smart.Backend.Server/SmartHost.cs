using System.Security.Cryptography;
using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Http;
using Microsoft.Extensions.Logging;

namespace Smart.Backend.Server;

public sealed record SmartHostOptions
{
    /// <summary>Where callers reach this host, ending in a slash. The token endpoint is oauth/token and the FHIR base is fhir/ under it.</summary>
    public required Uri PublicBase { get; init; }
    /// <summary>The FHIR server behind the gateway, ending in a slash.</summary>
    public required Uri UpstreamFhirBase { get; init; }
    public required IReadOnlyDictionary<string, ClientRegistration> Clients { get; init; }
    public required Action<AuditEvent> Audit { get; init; }
    public TimeProvider Clock { get; init; } = TimeProvider.System;
}

/// <summary>A token endpoint and a FHIR gateway in one process, for the sample. In production these are usually two deployments.</summary>
public static class SmartHost
{
    public static WebApplication Build(SmartHostOptions options, out JwksResolver jwks)
    {
        Uri tokenEndpoint = new(options.PublicBase, "oauth/token"), fhirBase = new(options.PublicBase, "fhir/");
        // The signing key lives as long as the process. Tokens last five minutes, so a restart costs clients one 401 and one retry.
        AccessTokens tokens = new(ECDsa.Create(ECCurve.NamedCurves.nistP384), options.PublicBase, fhirBase, options.Clock);
        JwksResolver resolver = jwks = new(new HttpClient { Timeout = TimeSpan.FromSeconds(5) }, options.Clock);
        TokenService service = new(options.Clients, resolver, tokens, tokenEndpoint, options.Clock, options.Audit);
        FhirGateway gateway = new(new HttpClient { Timeout = TimeSpan.FromSeconds(100) }, options.UpstreamFhirBase, fhirBase, tokenEndpoint, tokens, options.Clock, options.Audit);

        WebApplicationBuilder builder = WebApplication.CreateSlimBuilder();
        builder.Logging.ClearProviders();
        builder.WebHost.UseUrls(options.PublicBase.GetLeftPart(UriPartial.Authority));
        WebApplication app = builder.Build();

        app.MapPost("/oauth/token", async (HttpContext http) =>
        {
            // A token response must never be stored by anything between the two parties.
            http.Response.Headers.CacheControl = "no-store";
            http.Response.Headers.Pragma = "no-cache";
            TokenResult result;
            if (!http.Request.HasFormContentType) { result = new TokenResult(400, new() { ["error"] = "invalid_request", ["error_description"] = "the body must be application/x-www-form-urlencoded" }); }
            else
            {
                IFormCollection form = await http.Request.ReadFormAsync(http.RequestAborted);
                result = form.Any(field => field.Value.Count > 1)
                    ? new TokenResult(400, new() { ["error"] = "invalid_request", ["error_description"] = "a parameter is repeated" })
                    : await service.HandleAsync(form.ToDictionary(field => field.Key, field => field.Value.ToString()), http.RequestAborted);
            }
            return Results.Text(result.Body.ToJsonString(), "application/json", statusCode: result.Status);
        });
        app.MapGet("/oauth/jwks", () => Results.Text(tokens.Jwks.ToJsonString(), "application/json"));
        app.Map("/fhir/{**path}", gateway.HandleAsync);
        return app;
    }
}
