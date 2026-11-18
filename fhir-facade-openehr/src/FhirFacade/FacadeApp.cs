using System.Security.Claims;
using System.Text.Json.Nodes;
using FhirFacade.Auth;
using FhirFacade.Fhir;
using FhirFacade.OpenEhr;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Diagnostics;
using Microsoft.Extensions.Options;

namespace FhirFacade;

/// <summary>Everything except token validation, which Program.cs configures for the host it runs on.</summary>
public static class FacadeApp
{
    private const string ResourceType = "Observation";

    public static IServiceCollection AddFacade(this IServiceCollection services, IConfiguration configuration)
    {
        services.AddOptions<OpenEhrOptions>().Bind(configuration.GetSection("OpenEhr")).ValidateDataAnnotations().ValidateOnStart();
        services.AddOptions<FhirOptions>().Bind(configuration.GetSection("Fhir")).ValidateDataAnnotations().ValidateOnStart();

        services.AddHttpClient<OpenEhrClient>((provider, client) =>
        {
            OpenEhrOptions options = provider.GetRequiredService<IOptions<OpenEhrOptions>>().Value;
            client.BaseAddress = options.BaseUrl;
            client.Timeout = TimeSpan.FromSeconds(options.TimeoutSeconds);
            client.DefaultRequestHeaders.Accept.ParseAdd("application/json");
        });

        // Every endpoint needs an authenticated caller unless it opts out explicitly.
        services.AddAuthorizationBuilder()
            .SetFallbackPolicy(new AuthorizationPolicyBuilder().RequireAuthenticatedUser().Build());
        return services;
    }

    public static WebApplication MapFacade(this WebApplication app)
    {
        app.UseExceptionHandler(handler => handler.Run(HandleErrorAsync));
        app.UseAuthentication();
        app.UseAuthorization();

        app.MapGet("/healthz", () => Results.Ok()).AllowAnonymous();
        RouteGroupBuilder fhir = app.MapGroup("/fhir");
        fhir.MapGet("/metadata", Metadata).AllowAnonymous();
        fhir.MapGet("/Observation", SearchAsync);
        fhir.MapGet("/Observation/{id}", ReadAsync);
        return app;
    }

    private static async Task<IResult> SearchAsync(
        HttpContext context, OpenEhrClient openEhr, IOptions<FhirOptions> fhirOptions,
        IOptions<OpenEhrOptions> openEhrOptions, ILoggerFactory loggers, CancellationToken cancellationToken)
    {
        ILogger logger = loggers.CreateLogger("FhirFacade.Audit");
        if (!SearchRequest.TryParse(context.Request.Query, fhirOptions.Value, out SearchRequest? search, out string error))
        {
            return FhirResults.Outcome(StatusCodes.Status400BadRequest, "invalid", error);
        }

        AccessDecision decision = SmartAccess.Evaluate(context.User, ResourceType, SmartPermissions.Search, search!.PatientId);
        if (!decision.Allowed)
        {
            AuditLog.Denied(logger, "search", search.PatientId, Subject(context.User), Client(context.User), decision.Reason);
            return FhirResults.Outcome(StatusCodes.Status403Forbidden, "forbidden", decision.Reason);
        }

        // Ask for one row more than the page holds: its presence is what says there is a next page.
        IReadOnlyList<BloodPressureRow> rows = await openEhr.QueryAsync(
            BloodPressureQuery.Search(search.PatientId, openEhrOptions.Value.SubjectNamespace,
                search.From, search.Before, search.NewestFirst, search.Count + 1, search.Offset),
            cancellationToken);

        if (rows.Any(row => row.PatientId != search.PatientId))
        {
            // The query filters on the patient. A row for anyone else means the filter did not hold.
            throw new MappingException("the repository returned a row for a different patient");
        }

        IReadOnlyList<JsonObject> observations = ObservationMapper.ToObservations(rows.Take(search.Count));
        string baseUrl = fhirOptions.Value.PublicBaseUrl!.ToString().TrimEnd('/');
        JsonArray links = [Link("self", $"{baseUrl}/{ResourceType}?{search.ToQueryString(search.Offset)}")];
        if (rows.Count > search.Count)
        {
            links.Add(Link("next", $"{baseUrl}/{ResourceType}?{search.ToQueryString(search.Offset + search.Count)}"));
        }

        JsonArray entries = [];
        foreach (JsonObject observation in observations)
        {
            entries.Add(new JsonObject
            {
                ["fullUrl"] = $"{baseUrl}/{ResourceType}/{(string)observation["id"]!}",
                ["resource"] = observation,
                ["search"] = new JsonObject { ["mode"] = "match" },
            });
        }

        AuditLog.Allowed(logger, "search", search.PatientId, Subject(context.User), Client(context.User),
            decision.Reason, observations.Count);
        return FhirResults.Resource(new JsonObject
        {
            ["resourceType"] = "Bundle",
            ["type"] = "searchset",
            ["link"] = links,
            ["entry"] = entries,
        });
    }

    private static async Task<IResult> ReadAsync(
        string id, HttpContext context, OpenEhrClient openEhr, ILoggerFactory loggers, CancellationToken cancellationToken)
    {
        ILogger logger = loggers.CreateLogger("FhirFacade.Audit");
        IResult notFound = FhirResults.Outcome(StatusCodes.Status404NotFound, "not-found", $"{ResourceType}/{id} was not found.");

        // Without any scope that allows a read there is no reason to touch the repository at all.
        if (!SmartAccess.ScopesOf(context.User).Any(scope => scope.Covers(ResourceType, SmartPermissions.Read)))
        {
            const string reason = "the token carries no scope that allows this interaction";
            AuditLog.Denied(logger, "read", "unknown", Subject(context.User), Client(context.User), reason);
            return FhirResults.Outcome(StatusCodes.Status403Forbidden, "forbidden", reason);
        }

        if (!ObservationMapper.TryParseLogicalId(id, out Guid ehrId, out Guid compositionId))
        {
            return notFound;
        }

        string? versionUid = await openEhr.LatestVersionUidAsync(ehrId, compositionId, cancellationToken);
        if (versionUid is null)
        {
            return notFound;
        }

        IReadOnlyList<BloodPressureRow> rows = await openEhr.QueryAsync(
            BloodPressureQuery.ByComposition(ehrId, versionUid), cancellationToken);
        if (rows.Count == 0)
        {
            return notFound; // The composition exists but holds no blood pressure.
        }

        JsonObject observation = ObservationMapper.ToObservations(rows)[0];
        string patientId = rows[0].PatientId!;
        AccessDecision decision = SmartAccess.Evaluate(context.User, ResourceType, SmartPermissions.Read, patientId);
        if (!decision.Allowed)
        {
            // Another patient's reading is reported as not found, so the answer does not confirm it exists.
            AuditLog.Denied(logger, "read", patientId, Subject(context.User), Client(context.User), decision.Reason);
            return notFound;
        }

        AuditLog.Allowed(logger, "read", patientId, Subject(context.User), Client(context.User), decision.Reason, 1);
        return FhirResults.Resource(observation);
    }

    private static IResult Metadata(IOptions<FhirOptions> fhirOptions) => FhirResults.Resource(new JsonObject
    {
        ["resourceType"] = "CapabilityStatement",
        ["status"] = "active",
        ["date"] = "2026-08-15",
        ["kind"] = "instance",
        ["software"] = new JsonObject { ["name"] = "FHIR facade over openEHR (sample)" },
        ["implementation"] = new JsonObject
        {
            ["description"] = "Read-only blood pressure Observations served from an openEHR repository",
            ["url"] = fhirOptions.Value.PublicBaseUrl!.ToString().TrimEnd('/'),
        },
        ["fhirVersion"] = "4.0.1",
        ["format"] = new JsonArray("application/fhir+json"),
        ["rest"] = new JsonArray(new JsonObject
        {
            ["mode"] = "server",
            ["security"] = new JsonObject
            {
                ["description"] = "OAuth 2.0 bearer token with SMART on FHIR patient/ or system/ scopes for Observation. " +
                                  "user/ scopes and scopes with query constraints are refused.",
            },
            ["resource"] = new JsonArray(new JsonObject
            {
                ["type"] = ResourceType,
                ["interaction"] = new JsonArray(
                    new JsonObject { ["code"] = "read" }, new JsonObject { ["code"] = "search-type" }),
                ["searchParam"] = new JsonArray(
                    SearchParam("patient", "reference", "Required. One patient."),
                    SearchParam("code", "token", "Required. Only http://loinc.org|85354-9."),
                    SearchParam("date", "date", "ge and lt, each with a full date, time and offset."),
                    SearchParam("_sort", "special", "date or -date (default)."),
                    SearchParam("_count", "number", "Page size."),
                    SearchParam("_offset", "number", "Used by the next link.")),
            }),
        }),
    });

    private static async Task HandleErrorAsync(HttpContext context)
    {
        Exception? error = context.Features.Get<IExceptionHandlerFeature>()?.Error;
        (int status, string code, string text) = error switch
        {
            OpenEhrUnavailableException => (StatusCodes.Status502BadGateway, "transient", "The clinical data repository is not available."),
            MappingException => (StatusCodes.Status500InternalServerError, "processing", "A record could not be represented in FHIR. Nothing was returned."),
            _ => (StatusCodes.Status500InternalServerError, "exception", "The request could not be processed."),
        };
        await FhirResults.WriteOutcomeAsync(context, status, code, text);
    }

    private static JsonObject Link(string relation, string url) => new() { ["relation"] = relation, ["url"] = url };

    private static JsonObject SearchParam(string name, string type, string documentation) =>
        new() { ["name"] = name, ["type"] = type, ["documentation"] = documentation };

    private static string Subject(ClaimsPrincipal user) => user.FindFirst("oid")?.Value ?? user.FindFirst("sub")?.Value ?? "unknown";

    private static string Client(ClaimsPrincipal user) => user.FindFirst("azp")?.Value ?? user.FindFirst("appid")?.Value ?? "unknown";
}
