using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;

namespace ClinicalCoding.Core;

/// <summary>Writes FHIR R4 for accepted items only: the resources and one Provenance naming the reviewer and the device.</summary>
public static class FhirMapper
{
    private const string Snomed = "http://snomed.info/sct";
    private const string Loinc = "http://loinc.org";
    private const string Ucum = "http://unitsofmeasure.org";

    public static JsonObject ToTransactionBundle(IReadOnlyList<AcceptedItem> accepted, NoteContext note, ReviewContext review, CodingSubset subset)
    {
        JsonArray entries = [];
        JsonArray targets = [];
        foreach (AcceptedItem item in accepted)
        {
            Proposal proposal = item.Proposal;
            string uuid = StableUuid(note.Document, proposal.Kind, item.Code, proposal.Evidence);
            JsonObject resource = proposal.Kind == "condition"
                ? new JsonObject
                {
                    ["resourceType"] = "Condition",
                    ["clinicalStatus"] = Concept("http://terminology.hl7.org/CodeSystem/condition-clinical", "active"),
                    ["verificationStatus"] = Concept("http://terminology.hl7.org/CodeSystem/condition-ver-status", item.Verification),
                    ["category"] = new JsonArray(Concept("http://terminology.hl7.org/CodeSystem/condition-category", "encounter-diagnosis")),
                    ["code"] = Concept(Snomed, item.Code, item.Display),
                    ["subject"] = Reference(note.Patient),
                    ["recordedDate"] = review.At,
                    ["asserter"] = Reference(review.Reviewer),
                    ["note"] = Source(proposal.Evidence),
                }
                : new JsonObject
                {
                    ["resourceType"] = "Observation",
                    ["status"] = "final",
                    ["category"] = new JsonArray(Concept("http://terminology.hl7.org/CodeSystem/observation-category", subset.Observation(item.Code)!.Category)),
                    ["code"] = Concept(Loinc, item.Code, item.Display),
                    ["subject"] = Reference(note.Patient),
                    ["effectiveDateTime"] = note.Date,
                    ["performer"] = new JsonArray(Reference(review.Reviewer)),
                    ["valueQuantity"] = new JsonObject { ["value"] = proposal.Value!.Value, ["unit"] = proposal.Unit, ["system"] = Ucum, ["code"] = proposal.Unit },
                    ["note"] = Source(proposal.Evidence),
                };
            targets.Add(Reference($"urn:uuid:{uuid}"));
            entries.Add(Entry(uuid, resource));
        }

        if (entries.Count > 0)
        {
            const string participant = "http://terminology.hl7.org/CodeSystem/provenance-participant-type";
            JsonObject provenance = new()
            {
                ["resourceType"] = "Provenance",
                ["target"] = targets,
                ["recorded"] = review.At,
                ["agent"] = new JsonArray(
                    new JsonObject { ["type"] = Concept(participant, "verifier"), ["who"] = Reference(review.Reviewer) },
                    new JsonObject { ["type"] = Concept(participant, "assembler"), ["who"] = Reference(review.Device) }),
                ["entity"] = new JsonArray(new JsonObject { ["role"] = "source", ["what"] = Reference(note.Document) }),
            };
            entries.Add(Entry(StableUuid(note.Document, "provenance", review.At), provenance));
        }

        return new JsonObject { ["resourceType"] = "Bundle", ["type"] = "transaction", ["entry"] = entries };
    }

    /// <summary>The same accepted item always gets the same identifier, so a repeated submission can be recognised.</summary>
    public static string StableUuid(params string[] parts)
    {
        string digest = Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(string.Join('|', parts))));
        return $"{digest[..8]}-{digest[8..12]}-{digest[12..16]}-{digest[16..20]}-{digest[20..32]}";
    }

    private static JsonObject Entry(string uuid, JsonObject resource) => new()
    {
        ["fullUrl"] = $"urn:uuid:{uuid}",
        ["resource"] = resource,
        ["request"] = new JsonObject { ["method"] = "POST", ["url"] = resource["resourceType"]!.GetValue<string>() },
    };

    private static JsonObject Concept(string system, string code, string? display = null)
    {
        JsonObject coding = new() { ["system"] = system, ["code"] = code };
        if (display is not null)
        {
            coding["display"] = display;
        }

        return new JsonObject { ["coding"] = new JsonArray(coding) };
    }

    private static JsonObject Reference(string reference) => new() { ["reference"] = reference };

    private static JsonObject Reference(Party party) => new() { ["reference"] = party.Reference, ["display"] = party.Display };

    private static JsonArray Source(string evidence) =>
        [new JsonObject { ["text"] = $"Source text: \"{ResponseGuard.Squash(evidence)}\"" }];
}
