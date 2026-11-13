using System.Net;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json.Nodes;

namespace Prescribing.Core;

public enum ApplyOutcome { Applied, Refused, Conflict, AlreadyApplied }

public sealed record ApplyResult(ApplyOutcome Outcome, Refusal Refusal = Refusal.None);

/// <summary>A prescription as read from the server, with the resource versions the next write must match.</summary>
public sealed record LoadedPrescription(
    Prescription Prescription, string RequestId, string RequestVersion, string TaskId, string TaskVersion, JsonObject Request, JsonObject Task);

/// <summary>
/// Maps the lifecycle onto FHIR R4. A prescription is a MedicationRequest plus one Task that tracks its
/// fulfilment; each supply is a MedicationDispense. Every transition is a single transaction Bundle whose
/// updates carry If-Match, so two actors who read the same version cannot both change it, and a transition
/// that touches several resources happens entirely or not at all.
/// </summary>
public sealed class FhirPrescriptionStore(HttpClient http, TimeProvider clock)
{
    public const string DispenseIdSystem = "https://example.org/fhir/dispense-id";
    private static readonly MediaTypeHeaderValue FhirJson = new("application/fhir+json");

    public async Task<LoadedPrescription> LoadAsync(string requestId, CancellationToken cancellationToken = default)
    {
        JsonObject request = await GetAsync($"MedicationRequest/{requestId}", cancellationToken);
        JsonObject tasks = await GetAsync($"Task?focus=MedicationRequest/{requestId}", cancellationToken);
        JsonObject task = tasks["entry"]![0]!["resource"]!.AsObject();
        JsonObject made = await GetAsync($"MedicationDispense?prescription=MedicationRequest/{requestId}&status=completed&_summary=count", cancellationToken);

        JsonNode dispenseRequest = request["dispenseRequest"]!;
        string? owner = task["owner"]?["reference"]?.GetValue<string>();
        PrescriptionState state = (request["status"]!.GetValue<string>(), task["status"]!.GetValue<string>()) switch
        {
            ("active", "requested") => PrescriptionState.Open,
            ("active", "accepted") => PrescriptionState.Claimed,
            ("completed", _) => PrescriptionState.Completed,
            ("cancelled", _) => PrescriptionState.Cancelled,
            ("stopped", _) => PrescriptionState.Expired,
            var other => throw new InvalidOperationException($"Unexpected status combination {other}."),
        };

        Prescription prescription = new(
            state, owner,
            SuppliesAllowed: 1 + (dispenseRequest["numberOfRepeatsAllowed"]?.GetValue<int>() ?? 0),
            SuppliesMade: made["total"]!.GetValue<int>(),
            ValidFrom: DateTimeOffset.Parse(dispenseRequest["validityPeriod"]!["start"]!.GetValue<string>()),
            ValidUntil: DateTimeOffset.Parse(dispenseRequest["validityPeriod"]!["end"]!.GetValue<string>()));
        return new LoadedPrescription(prescription, requestId, Version(request), task["id"]!.GetValue<string>(), Version(task), request, task);
    }

    /// <summary>
    /// Decides the command against what was loaded and, if it is allowed, writes the result. A Conflict means
    /// somebody else changed the prescription first: load again and decide again, never retry blindly.
    /// </summary>
    public async Task<ApplyResult> ApplyAsync(LoadedPrescription loaded, Command command, CancellationToken cancellationToken = default)
    {
        if (command is Command.Dispense repeat && await DispenseExistsAsync(repeat.DispenseId, cancellationToken))
        {
            return new ApplyResult(ApplyOutcome.AlreadyApplied);
        }

        DateTimeOffset now = clock.GetUtcNow();
        Decision decision = PrescriptionLifecycle.Decide(loaded.Prescription, command, now);
        if (!decision.Accepted)
        {
            return new ApplyResult(ApplyOutcome.Refused, decision.Refusal);
        }

        JsonArray entries = [];
        JsonObject task = loaded.Task.DeepClone().AsObject();
        task["status"] = decision.Next.State switch
        {
            PrescriptionState.Open => "requested",
            PrescriptionState.Claimed => "accepted",
            PrescriptionState.Completed => "completed",
            _ => "cancelled",
        };
        task["lastModified"] = Instant(now);
        task.Remove("owner");
        if (decision.Next.ClaimedBy is { } pharmacy)
        {
            task["owner"] = new JsonObject { ["reference"] = pharmacy };
        }

        entries.Add(Update(task, $"Task/{loaded.TaskId}", loaded.TaskVersion));

        string requestStatus = decision.Next.State switch
        {
            PrescriptionState.Completed => "completed",
            PrescriptionState.Cancelled => "cancelled",
            PrescriptionState.Expired => "stopped",
            _ => "active",
        };
        if (requestStatus != loaded.Request["status"]!.GetValue<string>())
        {
            JsonObject request = loaded.Request.DeepClone().AsObject();
            request["status"] = requestStatus;
            if (command is Command.Cancel cancel)
            {
                request["statusReason"] = new JsonObject { ["text"] = cancel.Reason };
            }

            entries.Add(Update(request, $"MedicationRequest/{loaded.RequestId}", loaded.RequestVersion));
        }

        if (command is Command.Dispense dispense)
        {
            entries.Add(new JsonObject
            {
                ["fullUrl"] = $"urn:uuid:{Guid.NewGuid()}",
                ["resource"] = new JsonObject
                {
                    ["resourceType"] = "MedicationDispense",
                    ["identifier"] = new JsonArray(new JsonObject { ["system"] = DispenseIdSystem, ["value"] = dispense.DispenseId }),
                    ["status"] = "completed",
                    ["medicationCodeableConcept"] = loaded.Request["medicationCodeableConcept"]!.DeepClone(),
                    ["subject"] = loaded.Request["subject"]!.DeepClone(),
                    ["performer"] = new JsonArray(new JsonObject { ["actor"] = new JsonObject { ["reference"] = dispense.Pharmacy } }),
                    ["authorizingPrescription"] = new JsonArray(new JsonObject { ["reference"] = $"MedicationRequest/{loaded.RequestId}" }),
                    ["quantity"] = loaded.Request["dispenseRequest"]!["quantity"]!.DeepClone(),
                    ["whenHandedOver"] = Instant(now),
                },
                ["request"] = new JsonObject
                {
                    ["method"] = "POST",
                    ["url"] = "MedicationDispense",
                    ["ifNoneExist"] = $"identifier={Uri.EscapeDataString($"{DispenseIdSystem}|{dispense.DispenseId}")}",
                },
            });
        }

        JsonObject bundle = new() { ["resourceType"] = "Bundle", ["type"] = "transaction", ["entry"] = entries };
        using StringContent content = new(bundle.ToJsonString(), Encoding.UTF8);
        content.Headers.ContentType = FhirJson;
        using HttpResponseMessage response = await http.PostAsync(string.Empty, content, cancellationToken);
        return response.StatusCode switch
        {
            HttpStatusCode.OK => new ApplyResult(ApplyOutcome.Applied),
            HttpStatusCode.Conflict or HttpStatusCode.PreconditionFailed => new ApplyResult(ApplyOutcome.Conflict),
            _ => throw new HttpRequestException($"The FHIR server refused the transaction with status {(int)response.StatusCode}.", null, response.StatusCode),
        };
    }

    private async Task<bool> DispenseExistsAsync(string dispenseId, CancellationToken cancellationToken)
    {
        JsonObject found = await GetAsync($"MedicationDispense?_summary=count&identifier={Uri.EscapeDataString($"{DispenseIdSystem}|{dispenseId}")}", cancellationToken);
        return found["total"]!.GetValue<int>() > 0;
    }

    private async Task<JsonObject> GetAsync(string relativeUrl, CancellationToken cancellationToken)
    {
        using HttpRequestMessage request = new(HttpMethod.Get, relativeUrl);
        request.Headers.Accept.ParseAdd("application/fhir+json");
        request.Headers.CacheControl = new CacheControlHeaderValue { NoCache = true };
        using HttpResponseMessage response = await http.SendAsync(request, cancellationToken);
        response.EnsureSuccessStatusCode();
        return JsonNode.Parse(await response.Content.ReadAsStringAsync(cancellationToken))!.AsObject();
    }

    private static JsonObject Update(JsonObject resource, string url, string version) => new()
    {
        ["fullUrl"] = url,
        ["resource"] = resource,
        ["request"] = new JsonObject { ["method"] = "PUT", ["url"] = url, ["ifMatch"] = $"W/\"{version}\"" },
    };

    private static string Version(JsonObject resource) => resource["meta"]!["versionId"]!.GetValue<string>();

    private static string Instant(DateTimeOffset value) => value.ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ss.fffZ");
}
