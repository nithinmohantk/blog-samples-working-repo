using System.Globalization;
using System.Net;
using System.Text;
using System.Text.Encodings.Web;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace AdtToFhir.Core;

public enum ApplyOutcome
{
    /// <summary>The transaction was accepted.</summary>
    Applied,
    /// <summary>This message was applied before. Nothing was sent.</summary>
    Duplicate,
    /// <summary>A later event for this patient is already on the server. Nothing was sent.</summary>
    Stale,
    /// <summary>The record this message addresses was merged into another one. Nothing was sent.</summary>
    PatientMerged,
    /// <summary>The patient changed between the read and the write. Read again and retry.</summary>
    Conflict,
    Failed,
}

/// <summary>What will be sent, or the decision not to send anything.</summary>
public sealed record Prepared(ApplyOutcome? Decided, string Detail, JsonObject? Bundle);

public sealed record ApplyResult(ApplyOutcome Outcome, string Detail, JsonObject? Sent);

public static class FhirJson
{
    public static readonly JsonSerializerOptions Indented = new() { WriteIndented = true, Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping };
}

/// <summary>
/// Applies a mapped message to a FHIR R4 server. The mapper knows the message; this class knows what the server
/// already holds, and adds the three decisions that need it: seen before, out of order, and merged away.
/// </summary>
public sealed class FhirApplier(HttpClient http)
{
    public async Task<ApplyResult> ApplyAsync(MapResult mapped, CancellationToken cancel = default)
    {
        Prepared prepared = await PrepareAsync(mapped, cancel);
        return prepared.Decided is ApplyOutcome decided ? new ApplyResult(decided, prepared.Detail, null) : await SendAsync(prepared, cancel);
    }

    public async Task<Prepared> PrepareAsync(MapResult mapped, CancellationToken cancel = default)
    {
        // 1. Seen before? The Provenance id is derived from the sender and MSH-10, so a resend finds its own record.
        if (await GetAsync($"Provenance/{mapped.ProvenanceId}", cancel) is not null)
        {
            return new Prepared(ApplyOutcome.Duplicate, $"message {mapped.ControlId} was applied before", null);
        }

        JsonObject bundle = (JsonObject)mapped.Bundle.DeepClone();
        JsonArray entries = bundle["entry"]!.AsArray();
        JsonObject patientEntry = entries[0]!.AsObject();
        JsonObject patient = patientEntry["resource"]!.AsObject();
        string placeholder = patientEntry["fullUrl"]!.GetValue<string>();
        string survivor = placeholder;

        JsonObject? current;
        try { current = await FindOneAsync("Patient", mapped.Patient, cancel); }
        catch (InvalidOperationException error) { return new Prepared(ApplyOutcome.Failed, error.Message, null); }

        if (current is not null)
        {
            string id = current["id"]!.GetValue<string>();

            // 2. Merged away? A retired record must not come back to life because an old feed still sends to it.
            if (current["active"]?.GetValue<bool>() == false && LinkOfType(current, "replaced-by") is string replacement)
            {
                return new Prepared(ApplyOutcome.PatientMerged, $"{mapped.Patient.Value} is retired and replaced by {replacement}", null);
            }

            // 3. Out of order? Compare the event time with the latest event already applied to this patient.
            if (await LatestEventAsync(id, cancel) is DateTimeOffset latest && latest > mapped.EventTime)
            {
                return new Prepared(ApplyOutcome.Stale, $"event of {mapped.EventTime:u} is older than {latest:u}, already applied", null);
            }

            // The update names the version that was just read. If another writer got in between, the server refuses.
            survivor = $"Patient/{id}";
            patient["id"] = id;
            patientEntry["fullUrl"] = new Uri(http.BaseAddress!, survivor).ToString();
            patientEntry["request"] = new JsonObject { ["method"] = "PUT", ["url"] = survivor, ["ifMatch"] = $"W/\"{current["meta"]!["versionId"]!.GetValue<string>()}\"" };
            // A v2 snapshot replaces what v2 owns. Links come from merges, not from PID, and must survive the update.
            if (current["link"] is JsonArray links) { patient["link"] = links.DeepClone(); }
            Repoint(entries, placeholder, survivor);
        }

        if (mapped.PriorPatient is ResourceKey priorKey)
        {
            JsonObject? prior;
            try { prior = await FindOneAsync("Patient", priorKey, cancel); }
            catch (InvalidOperationException error) { return new Prepared(ApplyOutcome.Failed, error.Message, null); }

            JsonObject retired, priorEntry;
            string priorReference;
            if (prior is not null)
            {
                string priorId = prior["id"]!.GetValue<string>();
                priorReference = $"Patient/{priorId}";
                retired = (JsonObject)prior.DeepClone();
                string version = retired["meta"]!["versionId"]!.GetValue<string>();
                retired.Remove("meta");
                priorEntry = new JsonObject
                {
                    ["fullUrl"] = new Uri(http.BaseAddress!, priorReference).ToString(),
                    ["resource"] = retired,
                    ["request"] = new JsonObject { ["method"] = "PUT", ["url"] = priorReference, ["ifMatch"] = $"W/\"{version}\"" },
                };
            }
            else
            {
                // The record to retire was never received. A stub keeps the old number resolvable and closed.
                priorReference = $"urn:uuid:{AdtMapper.Uuid($"patient|{priorKey}")}";
                retired = new JsonObject
                {
                    ["resourceType"] = "Patient",
                    ["identifier"] = new JsonArray(new JsonObject { ["system"] = priorKey.System, ["value"] = priorKey.Value }),
                };
                priorEntry = new JsonObject
                {
                    ["fullUrl"] = priorReference,
                    ["resource"] = retired,
                    ["request"] = new JsonObject { ["method"] = "PUT", ["url"] = $"Patient?{priorKey.Query}" },
                };
            }
            retired["active"] = false;
            AddLink(retired, survivor, "replaced-by");
            AddLink(patient, priorReference, "replaces");
            entries.Insert(1, priorEntry);
        }
        return new Prepared(null, "", bundle);
    }

    public async Task<ApplyResult> SendAsync(Prepared prepared, CancellationToken cancel = default)
    {
        using StringContent body = new(prepared.Bundle!.ToJsonString(), Encoding.UTF8, "application/fhir+json");
        using HttpResponseMessage response = await http.PostAsync("", body, cancel);
        if (response.IsSuccessStatusCode) { return new ApplyResult(ApplyOutcome.Applied, "", prepared.Bundle); }
        string text = await response.Content.ReadAsStringAsync(cancel);
        string detail = $"HTTP {(int)response.StatusCode}: {Diagnostics(text)}";
        bool conflict = response.StatusCode is HttpStatusCode.Conflict or HttpStatusCode.PreconditionFailed;
        return new ApplyResult(conflict ? ApplyOutcome.Conflict : ApplyOutcome.Failed, detail, prepared.Bundle);
    }

    private async Task<JsonObject?> FindOneAsync(string type, ResourceKey key, CancellationToken cancel)
    {
        JsonObject found = await GetAsync($"{type}?{key.Query}", cancel) ?? throw new InvalidOperationException($"The search for {type} {key.Value} failed.");
        List<JsonObject> matches = [.. (found["entry"]?.AsArray() ?? []).Select(e => e!["resource"]!.AsObject()).Where(r => r["resourceType"]!.GetValue<string>() == type)];
        return matches.Count switch
        {
            0 => null,
            1 => matches[0],
            _ => throw new InvalidOperationException($"{matches.Count} {type} resources carry identifier {key.Value}; a person has to resolve that before more messages are applied."),
        };
    }

    private async Task<DateTimeOffset?> LatestEventAsync(string patientId, CancellationToken cancel)
    {
        JsonObject? found = await GetAsync($"Provenance?target=Patient/{patientId}&_sort=-when&_count=1", cancel);
        string? occurred = found?["entry"]?.AsArray().FirstOrDefault()?["resource"]?["occurredDateTime"]?.GetValue<string>();
        return occurred is null ? null : DateTimeOffset.Parse(occurred, CultureInfo.InvariantCulture);
    }

    private async Task<JsonObject?> GetAsync(string relativeUrl, CancellationToken cancel)
    {
        using HttpRequestMessage request = new(HttpMethod.Get, relativeUrl);
        request.Headers.TryAddWithoutValidation("Accept", "application/fhir+json");
        // Without this a server may answer a repeated search from a cache and hide a write made a moment ago.
        request.Headers.TryAddWithoutValidation("Cache-Control", "no-cache");
        using HttpResponseMessage response = await http.SendAsync(request, cancel);
        if (response.StatusCode is HttpStatusCode.NotFound or HttpStatusCode.Gone) { return null; }
        response.EnsureSuccessStatusCode();
        return JsonNode.Parse(await response.Content.ReadAsStringAsync(cancel))!.AsObject();
    }

    private static string? LinkOfType(JsonObject patient, string type) =>
        patient["link"]?.AsArray().FirstOrDefault(l => l!["type"]!.GetValue<string>() == type)?["other"]?["reference"]?.GetValue<string>();

    private static void AddLink(JsonObject patient, string other, string type)
    {
        JsonArray links = patient["link"] as JsonArray ?? [];
        if (!links.Any(l => l!["other"]?["reference"]?.GetValue<string>() == other && l["type"]?.GetValue<string>() == type))
        {
            links.Add(new JsonObject { ["other"] = new JsonObject { ["reference"] = other }, ["type"] = type });
        }
        if (links.Parent is null) { patient["link"] = links; }
    }

    /// <summary>Rewrites every reference to a placeholder so it names the resource the server already holds.</summary>
    private static void Repoint(JsonNode? node, string from, string to)
    {
        switch (node)
        {
            case JsonObject item:
                if (item["reference"] is JsonValue value && value.TryGetValue(out string? reference) && reference == from) { item["reference"] = to; }
                foreach (KeyValuePair<string, JsonNode?> child in item.ToList()) { Repoint(child.Value, from, to); }
                break;
            case JsonArray list:
                foreach (JsonNode? child in list) { Repoint(child, from, to); }
                break;
        }
    }

    private static string Diagnostics(string body)
    {
        try
        {
            string? text = JsonNode.Parse(body)?["issue"]?.AsArray().FirstOrDefault()?["diagnostics"]?.GetValue<string>();
            return text ?? body[..Math.Min(body.Length, 300)];
        }
        catch (JsonException) { return body[..Math.Min(body.Length, 300)]; }
    }
}
