// One regional instance of the booking API. The same build runs in every region; REGION_NAME says which.
// Storage here is process memory so the sample runs anywhere. In a deployment it is the regional
// endpoint of a multi-region database, and the idempotency key is stored with the booking.
using System.Collections.Concurrent;
using ActiveActive.Core;

WebApplicationBuilder builder = WebApplication.CreateBuilder(args);
builder.Logging.ClearProviders();
builder.Logging.AddJsonConsole();
WebApplication app = builder.Build();

string region = Environment.GetEnvironmentVariable("REGION_NAME") ?? "local";
IdempotentCommands commands = new();
ConcurrentDictionary<string, string> bookings = new(StringComparer.Ordinal);
bool draining = false;

// Every response says which region produced it. During a drill this is how you see traffic move.
app.Use(async (context, next) =>
{
    context.Response.Headers["x-region"] = region;
    await next(context);
});

// Liveness: is the process running. Cheap, no dependencies, never used for global routing.
app.MapGet("/healthz", () => Results.Ok(new { status = "ok", region }));

// Readiness: what the global load balancer probes. See Readiness for the rule.
app.MapGet("/ready", () =>
{
    ReadinessVerdict verdict = Readiness.Evaluate(new RegionState(DatabaseReachable: true, AcceptingWrites: true, ReplicationLag: TimeSpan.Zero, Draining: draining));
    return verdict.Ready ? Results.Ok(new { verdict.Reason, region }) : Results.Json(new { verdict.Reason, region }, statusCode: StatusCodes.Status503ServiceUnavailable);
});

// Take this region out of rotation on purpose, for a deployment or a failover drill.
app.MapPost("/admin/drain", () => { draining = true; return Results.Accepted(); });

app.MapPost("/bookings", (BookingRequest request, HttpContext context, ILogger<Program> logger) =>
{
    string? key = context.Request.Headers["Idempotency-Key"];
    if (string.IsNullOrWhiteSpace(key))
    {
        return Results.Problem("An Idempotency-Key header is required: a retry may be served by another region.", statusCode: StatusCodes.Status400BadRequest);
    }

    if (string.IsNullOrWhiteSpace(request.SlotId) || string.IsNullOrWhiteSpace(request.PatientReference))
    {
        return Results.Problem("slotId and patientReference are required.", statusCode: StatusCodes.Status400BadRequest);
    }

    CommandOutcome outcome = commands.Execute(key, () =>
        bookings.TryAdd(request.SlotId, request.PatientReference)
            ? new CommandOutcome(StatusCodes.Status201Created, $$"""{"slotId":"{{request.SlotId}}","status":"booked"}""", region)
            : new CommandOutcome(StatusCodes.Status409Conflict, $$"""{"slotId":"{{request.SlotId}}","status":"taken"}""", region));

    // Identifiers only. The patient reference is not written to the log.
    logger.LogInformation("booking {SlotId} {Status} decided-in {DecidedIn}", request.SlotId, outcome.StatusCode, outcome.Region);
    context.Response.Headers["x-decided-in"] = outcome.Region;
    return Results.Content(outcome.Body, "application/json", statusCode: outcome.StatusCode);
});

app.Run();

internal sealed record BookingRequest(string SlotId, string PatientReference);
