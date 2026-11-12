using System.Text.Json;
using System.Text.Json.Nodes;

namespace FhirFacade.Fhir;

public static class FhirResults
{
    public const string ContentType = "application/fhir+json; charset=utf-8";

    public static IResult Resource(JsonObject resource, int statusCode = StatusCodes.Status200OK) =>
        Results.Text(resource.ToJsonString(), ContentType, statusCode: statusCode);

    /// <param name="code">A value from the FHIR issue-type value set, for example "forbidden" or "not-found".</param>
    /// <param name="diagnostics">Safe for the caller to read. Never backend messages or patient data.</param>
    public static IResult Outcome(int statusCode, string code, string diagnostics) => Resource(
        new JsonObject
        {
            ["resourceType"] = "OperationOutcome",
            ["issue"] = new JsonArray(new JsonObject
            {
                ["severity"] = "error",
                ["code"] = code,
                ["diagnostics"] = diagnostics,
            }),
        },
        statusCode);

    public static Task WriteOutcomeAsync(HttpContext context, int statusCode, string code, string diagnostics) =>
        Outcome(statusCode, code, diagnostics).ExecuteAsync(context);
}
