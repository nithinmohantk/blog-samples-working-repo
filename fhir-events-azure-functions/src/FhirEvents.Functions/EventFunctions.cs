using System.Net;
using System.Text.Json.Nodes;
using FhirEvents.Core;
using Microsoft.Azure.Functions.Worker;
using Microsoft.Azure.Functions.Worker.Http;
using Microsoft.Extensions.Logging;

namespace FhirEvents.Functions;

public sealed class EventFunctions(FhirChangeHandler handler, IProjectionStore store, ILogger<EventFunctions> logger)
{
    /// <summary>
    /// The Event Grid subscription's handler. An exception fails the invocation, and Event Grid then delivers
    /// the event again under its retry policy. Malformed events are logged and dropped: retrying cannot fix them.
    /// </summary>
    [Function("ProjectFromEventGrid")]
    public async Task FromEventGrid([EventGridTrigger] string eventJson, CancellationToken cancellationToken) =>
        await ApplyAsync(eventJson, cancellationToken);

    /// <summary>
    /// The same processing behind an HTTP endpoint, for deliveries that arrive through a gateway instead of
    /// directly from Event Grid. It answers both subscription validation handshakes.
    /// </summary>
    [Function("ProjectFromWebhook")]
    public async Task<HttpResponseData> FromWebhook(
        [HttpTrigger(AuthorizationLevel.Function, "post", "options", Route = "events")] HttpRequestData request,
        CancellationToken cancellationToken)
    {
        // CloudEvents handshake: an OPTIONS request naming the origin that wants to deliver.
        if (request.Method.Equals("OPTIONS", StringComparison.OrdinalIgnoreCase))
        {
            HttpResponseData allowed = request.CreateResponse(HttpStatusCode.OK);
            if (request.Headers.TryGetValues("WebHook-Request-Origin", out IEnumerable<string>? origins))
            {
                allowed.Headers.Add("WebHook-Allowed-Origin", origins.First());
            }

            return allowed;
        }

        string body = await new StreamReader(request.Body).ReadToEndAsync(cancellationToken);

        // Event Grid schema handshake: echo the validation code.
        if (TryGetValidationCode(body) is { } code)
        {
            return await JsonAsync(request, new JsonObject { ["validationResponse"] = code });
        }

        return await JsonAsync(request, await ApplyAsync(body, cancellationToken));
    }

    /// <summary>Reads one row of the projection. Used by the test client to see what the events produced.</summary>
    [Function("GetProjection")]
    public async Task<HttpResponseData> GetProjection(
        [HttpTrigger(AuthorizationLevel.Function, "get", Route = "projection/{id}")] HttpRequestData request,
        string id, CancellationToken cancellationToken)
    {
        ProjectionRow? row = await store.GetAsync(FhirChangeHandler.ProjectedType, id, cancellationToken);
        if (row is null)
        {
            return request.CreateResponse(HttpStatusCode.NotFound);
        }

        return await JsonAsync(request, new JsonObject
        {
            ["resourceId"] = row.ResourceId,
            ["version"] = row.Version,
            ["deleted"] = row.Deleted,
            ["retracted"] = row.Retracted,
            ["patientId"] = row.PatientId,
            ["effective"] = row.Effective,
            ["systolic"] = row.Systolic,
            ["diastolic"] = row.Diastolic,
        });
    }

    private async Task<JsonObject> ApplyAsync(string delivery, CancellationToken cancellationToken)
    {
        (IReadOnlyList<FhirChangeEvent> events, IReadOnlyList<string> rejected) = FhirChangeEvent.ParseDelivery(delivery);
        foreach (string reason in rejected)
        {
            logger.LogWarning("Dropped an event that cannot be processed: {Reason}", reason);
        }

        JsonArray results = [];
        foreach (FhirChangeEvent change in events)
        {
            Outcome outcome = await handler.HandleAsync(change, cancellationToken);
            // Resource type, id and version are identifiers, not clinical content. Nothing else is logged.
            logger.LogInformation("Event {EventId} {Kind} {ResourceType}/{ResourceId} v{Version}: {Outcome}",
                change.EventId, change.Kind, change.ResourceType, change.ResourceId, change.Version, outcome);
            results.Add(new JsonObject { ["eventId"] = change.EventId, ["outcome"] = outcome.ToString() });
        }

        return new JsonObject { ["results"] = results, ["rejected"] = new JsonArray([.. rejected.Select(r => (JsonNode)r)]) };
    }

    private static string? TryGetValidationCode(string body)
    {
        try
        {
            return JsonNode.Parse(body) is JsonArray { Count: 1 } events
                && (string?)events[0]?["eventType"] == "Microsoft.EventGrid.SubscriptionValidationEvent"
                ? (string?)events[0]?["data"]?["validationCode"]
                : null;
        }
        catch (System.Text.Json.JsonException)
        {
            return null;
        }
    }

    private static async Task<HttpResponseData> JsonAsync(HttpRequestData request, JsonObject body)
    {
        HttpResponseData response = request.CreateResponse(HttpStatusCode.OK);
        response.Headers.Add("Content-Type", "application/json");
        await response.WriteStringAsync(body.ToJsonString());
        return response;
    }
}
