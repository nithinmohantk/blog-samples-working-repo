using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;

namespace AdtToFhir.Core;

/// <summary>The message was readable but cannot be converted. AckCode is AE (fix and resend) or AR (never supported).</summary>
public sealed class MappingException(string ackCode, string message) : Exception(message)
{
    public string AckCode { get; } = ackCode;
}

public sealed record MapperOptions
{
    /// <summary>
    /// "assigning authority|identifier type" to the system URI, for example "GENHOSP|MR". The authority alone is
    /// not enough: one hospital issues record numbers, visit numbers and staff numbers from different sequences.
    /// </summary>
    public required IReadOnlyDictionary<string, string> IdentifierSystems { get; init; }

    /// <summary>Applied to a time of day that arrives with no offset when MSH-7 has none either.</summary>
    public TimeSpan? DefaultOffset { get; init; }
}

/// <summary>A business identifier that a resource is matched on.</summary>
public sealed record ResourceKey(string System, string Value)
{
    public string Query => $"identifier={Uri.EscapeDataString($"{System}|{Value}")}";
    public override string ToString() => $"{System}|{Value}";
}

/// <param name="Replaces">
/// The parts of the Patient this message speaks for, because it sent a value or an explicit null for them.
/// Everything else on a patient the server already holds is left as it is.
/// </param>
public sealed record MapResult(
    string ControlId, string Trigger, DateTimeOffset EventTime, string ProvenanceId,
    ResourceKey Patient, ResourceKey? PriorPatient, ResourceKey? Visit, IReadOnlyList<string> Replaces,
    JsonObject Bundle, IReadOnlyList<string> Notes);

/// <summary>
/// Converts one ADT message into one FHIR R4 transaction Bundle. It reads nothing but the message and its options,
/// so the same message always gives the same Bundle, byte for byte.
/// </summary>
public sealed class AdtMapper(MapperOptions options)
{
    public static readonly IReadOnlySet<string> SupportedTriggers = new HashSet<string> { "A01", "A03", "A04", "A08", "A11", "A40" };
    private static readonly Guid UuidNamespace = new("5b0f3f0e-6c0a-4d53-9d0b-6b1f6f0f7a11");
    private const string V2 = "http://terminology.hl7.org/CodeSystem/v2-";
    private const string UriSystem = "urn:ietf:rfc:3986";

    private static readonly Dictionary<string, string> Gender = new() { ["F"] = "female", ["M"] = "male", ["O"] = "other", ["A"] = "other", ["N"] = "other", ["U"] = "unknown" };
    private static readonly Dictionary<string, string> NameUse = new() { ["L"] = "official", ["D"] = "usual", ["M"] = "maiden", ["N"] = "nickname" };
    private static readonly Dictionary<string, string> IdentifierType = new() { ["MR"] = "Medical record number", ["PI"] = "Patient internal identifier", ["VN"] = "Visit number" };
    // Table 0002 and v3 MaritalStatus share letters that mean different things: v2 "A" is separated, v3 "A" is annulled.
    private static readonly Dictionary<string, (string Code, string? Display)> Marital = new()
    {
        ["M"] = ("M", "Married"), ["S"] = ("S", "Never Married"), ["D"] = ("D", "Divorced"), ["W"] = ("W", "Widowed"),
        ["N"] = ("A", null), ["E"] = ("L", null), ["P"] = ("T", null), ["I"] = ("I", null), ["B"] = ("U", null),
    };
    private static readonly Dictionary<string, (string Code, string Display)> EncounterClass = new()
    {
        ["E"] = ("EMER", "emergency"), ["I"] = ("IMP", "inpatient encounter"), ["O"] = ("AMB", "ambulatory"), ["P"] = ("PRENC", "pre-admission"),
    };
    private static readonly HashSet<string> OtherPatientClasses = ["R", "B", "C", "N", "U"];
    private static readonly Dictionary<string, string> ContactRole = new()
    {
        ["C"] = "Emergency Contact", ["E"] = "Employer", ["F"] = "Federal Agency", ["I"] = "Insurance Company", ["N"] = "Next-of-Kin", ["S"] = "State Agency", ["U"] = "Unknown",
    };
    private static readonly HashSet<string> Relationships = ["SPO", "MTH", "FTH", "CHD", "SIB", "BRO", "SIS", "FND", "GRD", "PAR", "DOM", "OTH", "UNK"];
    private static readonly Dictionary<string, string> AllergyCategory = new() { ["DA"] = "medication", ["FA"] = "food", ["EA"] = "environment" };
    private static readonly Dictionary<string, string> ReactionSeverity = new() { ["SV"] = "severe", ["MO"] = "moderate", ["MI"] = "mild" };
    private static readonly Dictionary<string, string> Criticality = new() { ["SV"] = "high", ["MO"] = "low", ["MI"] = "low", ["U"] = "unable-to-assess" };
    private static readonly Dictionary<string, string> CodeSystems = new() { ["SCT"] = "http://snomed.info/sct", ["LN"] = "http://loinc.org" };

    public MapResult Map(Hl7Message message, DateTimeOffset receivedAt)
    {
        Hl7Segment msh = message.First("MSH")!;
        if (message.MessageCode != "ADT" || !SupportedTriggers.Contains(message.TriggerEvent))
        {
            throw new MappingException("AR", $"{message.MessageCode}^{message.TriggerEvent} is not a message this interface converts.");
        }
        string trigger = message.TriggerEvent;
        List<string> notes = [];

        // One offset for the whole message: the one on MSH-7 if the sender gave it, the configured one if not.
        TimeSpan? offset = V2Time.Parse(msh.Value(7), null)?.Instant?.Offset ?? options.DefaultOffset;
        bool assumed = false;
        V2Time? Time(string value)
        {
            V2Time? parsed = V2Time.Parse(value, offset);
            if (parsed is null && value.Length > 0) { notes.Add($"'{value}' is not an HL7 v2 date or time and was left out."); }
            assumed |= parsed?.OffsetAssumed == true;
            return parsed;
        }

        Hl7Segment? evn = message.First("EVN");
        DateTimeOffset eventTime = Time(evn?.Value(6) ?? "")?.Instant ?? Time(evn?.Value(2) ?? "")?.Instant ?? Time(msh.Value(7))?.Instant
            ?? throw new MappingException("AE", "Neither EVN-6, EVN-2 nor MSH-7 carries a date and time, so the event cannot be ordered.");

        Hl7Segment pid = message.First("PID") ?? throw new MappingException("AE", "The message has no PID segment.");
        ResourceKey patientKey = PatientKey(pid, 3, notes) ?? throw new MappingException("AE", "PID-3 has no medical record number (type MR) from a known assigning authority.");
        string patientUrl = Urn($"patient|{patientKey}");
        JsonArray entries = [];

        JsonObject patient = Patient(pid, [.. message.All("NK1")], Time, notes);
        // An empty field says nothing; a value or two double quotes says "this is the state now".
        (string Slot, int Field)[] slots = [("name", 5), ("birthDate", 7), ("gender", 8), ("address", 11), ("telecom:home", 13), ("telecom:work", 14), ("maritalStatus", 16), ("deceased", 30)];
        List<string> replaces = [.. slots.Where(slot => pid.Raw(slot.Field).Length > 0).Select(slot => slot.Slot)];
        if (message.First("NK1") is not null) { replaces.Add("contact"); }
        entries.Add(Entry(patientUrl, patient, "PUT", $"Patient?{patientKey.Query}"));

        ResourceKey? prior = null;
        if (trigger == "A40")
        {
            Hl7Segment mrg = message.First("MRG") ?? throw new MappingException("AE", "A merge needs an MRG segment.");
            prior = PatientKey(mrg, 1, notes) ?? throw new MappingException("AE", "MRG-1 has no medical record number (type MR) from a known assigning authority.");
            if (prior == patientKey) { throw new MappingException("AE", "MRG-1 and PID-3 name the same record."); }
        }

        string? encounterUrl = null;
        ResourceKey? visitKey = null;
        Hl7Segment? pv1 = message.First("PV1");
        if (trigger is "A01" or "A03" or "A04" or "A11")
        {
            if (pv1 is null) { throw new MappingException("AE", $"{trigger} needs a PV1 segment."); }
            ResourceKey visit = Key(pv1, 19, 0, "VN") ?? throw new MappingException("AE", "PV1-19 has no visit number from a known assigning authority.");
            visitKey = visit;
            encounterUrl = Urn($"encounter|{visit}");
            entries.Add(Entry(encounterUrl, Encounter(pv1, trigger, visit, patientUrl, Time, notes), "PUT", $"Encounter?{visit.Query}"));
        }
        else if (pv1 is not null)
        {
            notes.Add($"PV1 is not applied on {trigger}: an encounter changes only through its own events.");
        }

        if (trigger is "A01" or "A04" or "A08")
        {
            foreach (Hl7Segment al1 in message.All("AL1"))
            {
                if (Allergy(al1, patientKey, patientUrl, Time, notes) is (JsonObject allergy, string identifier))
                {
                    entries.Add(Entry(identifier, allergy, "PUT", $"AllergyIntolerance?identifier={Uri.EscapeDataString($"{UriSystem}|{identifier}")}"));
                }
            }
        }

        string provenanceId = Uuid($"message|{msh.Value(3)}|{msh.Value(4)}|{message.ControlId}");
        JsonArray targets = [Reference(patientUrl)];
        if (encounterUrl is not null) { targets.Add(Reference(encounterUrl)); }
        JsonObject sourceIdentifier = new() { ["value"] = message.ControlId };
        if (options.IdentifierSystems.TryGetValue($"{msh.Value(4)}|MSG", out string? messageSystem)) { sourceIdentifier = new() { ["system"] = messageSystem, ["value"] = message.ControlId }; }
        JsonObject provenance = new()
        {
            ["resourceType"] = "Provenance",
            ["id"] = provenanceId,
            ["target"] = targets,
            ["occurredDateTime"] = eventTime.ToString("yyyy-MM-dd'T'HH:mm:sszzz", CultureInfo.InvariantCulture),
            ["recorded"] = receivedAt.ToUniversalTime().ToString("yyyy-MM-dd'T'HH:mm:ss'Z'", CultureInfo.InvariantCulture),
            ["activity"] = Concept(Coding($"{V2}0003", trigger)),
            ["agent"] = new JsonArray(new JsonObject { ["who"] = new JsonObject { ["display"] = $"{msh.Value(3)} at {msh.Value(4)}" } }),
            ["entity"] = new JsonArray(new JsonObject
            {
                ["role"] = "source",
                ["what"] = new JsonObject { ["identifier"] = sourceIdentifier, ["display"] = $"HL7 v{message.Version} {message.MessageCode}^{trigger}" },
            }),
        };
        entries.Add(Entry($"urn:uuid:{provenanceId}", provenance, "PUT", $"Provenance/{provenanceId}"));

        string[] handled = ["MSH", "EVN", "PID", "PV1", "NK1", "AL1", "MRG"];
        foreach (IGrouping<string, Hl7Segment> group in message.Segments.Where(s => !handled.Contains(s.Name)).GroupBy(s => s.Name))
        {
            notes.Add($"Segment {group.Key} is not mapped ({group.Count()} in this message).");
        }
        if (assumed) { notes.Add($"At least one time had no offset; {Format(offset!.Value)} was assumed."); }

        JsonObject bundle = new() { ["resourceType"] = "Bundle", ["type"] = "transaction", ["entry"] = entries };
        return new MapResult(message.ControlId, trigger, eventTime, provenanceId, patientKey, prior, visitKey, replaces, bundle, notes);
    }

    // ---- Patient -------------------------------------------------------------------------------------------

    private JsonObject Patient(Hl7Segment pid, IReadOnlyList<Hl7Segment> nextOfKin, Func<string, V2Time?> time, List<string> notes)
    {
        JsonObject patient = new() { ["resourceType"] = "Patient" };
        JsonArray identifiers = [];
        for (int r = 0; r < pid.RepetitionCount(3); r++)
        {
            string type = pid.Value(3, 5, 1, r) is { Length: > 0 } given ? given : "MR";
            if (Key(pid, 3, r, type) is not ResourceKey key)
            {
                notes.Add($"PID-3 repetition {r + 1} has an assigning authority and type with no configured system and was left out.");
                continue;
            }
            JsonObject identifier = new();
            if (IdentifierType.TryGetValue(type, out string? display)) { identifier["type"] = Concept(Coding($"{V2}0203", type, display)); }
            identifier["system"] = key.System;
            identifier["value"] = key.Value;
            identifiers.Add(identifier);
        }
        patient["identifier"] = identifiers;
        patient["active"] = true;

        JsonArray names = [];
        for (int r = 0; r < pid.RepetitionCount(5); r++) { if (Name(pid, 5, r, notes) is JsonObject name) { names.Add(name); } }
        if (names.Count > 0) { patient["name"] = names; }

        JsonArray telecom = [.. Telecom(pid, 13, "home"), .. Telecom(pid, 14, "work")];
        if (telecom.Count > 0) { patient["telecom"] = telecom; }

        string sex = pid.Value(8).ToUpperInvariant();
        if (sex.Length > 0)
        {
            if (!Gender.TryGetValue(sex, out string? gender)) { gender = "unknown"; notes.Add($"PID-8 '{pid.Value(8)}' is not in table 0001; gender is recorded as unknown."); }
            patient["gender"] = gender;
        }
        if (time(pid.Value(7)) is V2Time born) { patient["birthDate"] = born.DateOnly; }

        if (pid.Value(30) == "Y" && time(pid.Value(29)) is V2Time died) { patient["deceasedDateTime"] = died.Fhir; }
        else if (pid.Value(30) is "Y" or "N") { patient["deceasedBoolean"] = pid.Value(30) == "Y"; }

        JsonArray addresses = [];
        for (int r = 0; r < pid.RepetitionCount(11); r++) { if (Address(pid, 11, r) is JsonObject address) { addresses.Add(address); } }
        if (addresses.Count > 0) { patient["address"] = addresses; }

        string marital = pid.Value(16).ToUpperInvariant();
        if (Marital.TryGetValue(marital, out (string Code, string? Display) status))
        {
            patient["maritalStatus"] = Concept(Coding("http://terminology.hl7.org/CodeSystem/v3-MaritalStatus", status.Code, status.Display));
        }
        else if (marital.Length > 0)
        {
            patient["maritalStatus"] = new JsonObject { ["text"] = pid.Value(16, 2) is { Length: > 0 } text ? text : $"HL7 v2 table 0002 code {marital}" };
            notes.Add($"PID-16 '{marital}' has no equivalent in the FHIR marital status codes; it is carried as text.");
        }

        JsonArray contacts = [];
        foreach (Hl7Segment nk1 in nextOfKin)
        {
            JsonObject contact = new();
            string role = ContactRole.ContainsKey(nk1.Value(7)) ? nk1.Value(7) : "N";
            JsonArray relationship = [Concept(Coding($"{V2}0131", role, ContactRole[role]))];
            if (Relationships.Contains(nk1.Value(3)))
            {
                JsonObject kin = Concept(Coding($"{V2}0063", nk1.Value(3)));
                if (nk1.Value(3, 2).Length > 0) { kin["text"] = nk1.Value(3, 2); }
                relationship.Add(kin);
            }
            else if ((nk1.Value(3, 2) is { Length: > 0 } text ? text : nk1.Value(3)) is { Length: > 0 } label)
            {
                relationship.Add(new JsonObject { ["text"] = label });
            }
            contact["relationship"] = relationship;
            if (Name(nk1, 2, 0, notes) is JsonObject name) { name.Remove("use"); contact["name"] = name; }
            JsonArray reach = [.. Telecom(nk1, 5, "home"), .. Telecom(nk1, 6, "work")];
            if (reach.Count > 0) { contact["telecom"] = reach; }
            if (Address(nk1, 4, 0) is JsonObject address) { contact["address"] = address; }
            if (contact.ContainsKey("name") || contact.ContainsKey("telecom") || contact.ContainsKey("address")) { contacts.Add(contact); }
            else { notes.Add("An NK1 with no name, telephone or address was left out: FHIR requires at least one of them."); }
        }
        if (contacts.Count > 0) { patient["contact"] = contacts; }
        return patient;
    }

    private static JsonObject? Name(Hl7Segment segment, int field, int repetition, List<string> notes)
    {
        string V(int component) => segment.Value(field, component, 1, repetition);
        JsonObject name = new();
        string type = V(7);
        if (NameUse.TryGetValue(type, out string? use)) { name["use"] = use; }
        else if (type.Length > 0) { notes.Add($"{segment.Name}-{field} name type '{type}' has no FHIR name use; the name is kept without one."); }
        if (V(1).Length > 0) { name["family"] = V(1); }
        JsonArray given = [.. new[] { V(2), V(3) }.Where(v => v.Length > 0).Select(v => (JsonNode)v)];
        if (given.Count > 0) { name["given"] = given; }
        if (V(5).Length > 0) { name["prefix"] = new JsonArray(V(5)); }
        JsonArray suffix = [.. new[] { V(4), V(6) }.Where(v => v.Length > 0).Select(v => (JsonNode)v)];
        if (suffix.Count > 0) { name["suffix"] = suffix; }
        return name.ContainsKey("family") || name.ContainsKey("given") ? name : null;
    }

    private static JsonObject? Address(Hl7Segment segment, int field, int repetition)
    {
        string V(int component) => segment.Value(field, component, 1, repetition);
        JsonObject address = new();
        switch (V(7))
        {
            case "H": address["use"] = "home"; break;
            case "B" or "O": address["use"] = "work"; break;
            case "C": address["use"] = "temp"; break;
            case "M": address["type"] = "postal"; break;
        }
        JsonArray lines = [.. new[] { V(1), V(2) }.Where(v => v.Length > 0).Select(v => (JsonNode)v)];
        if (lines.Count > 0) { address["line"] = lines; }
        if (V(3).Length > 0) { address["city"] = V(3); }
        if (V(4).Length > 0) { address["state"] = V(4); }
        if (V(5).Length > 0) { address["postalCode"] = V(5); }
        if (V(6).Length > 0) { address["country"] = V(6); }
        return address.ContainsKey("line") || address.ContainsKey("city") || address.ContainsKey("postalCode") ? address : null;
    }

    private static IEnumerable<JsonNode> Telecom(Hl7Segment segment, int field, string use)
    {
        for (int r = 0; r < segment.RepetitionCount(field); r++)
        {
            string V(int component) => segment.Value(field, component, 1, r);
            string equipment = V(3);
            bool email = equipment is "Internet" or "X.400" || V(4).Length > 0;
            // XTN-12 is the unformatted number of v2.7; XTN-1 the free-text number of older versions; then the parts.
            string value = email ? V(4) : new[] { V(12), V(1), string.Concat(V(5), V(6), V(7)) }.FirstOrDefault(v => v.Length > 0) ?? "";
            if (value.Length == 0) { continue; }
            yield return new JsonObject
            {
                ["system"] = email ? "email" : equipment == "FX" ? "fax" : "phone",
                ["value"] = value,
                ["use"] = equipment == "CP" ? "mobile" : use,
            };
        }
    }

    // ---- Encounter -----------------------------------------------------------------------------------------

    private JsonObject Encounter(Hl7Segment pv1, string trigger, ResourceKey visit, string patientUrl, Func<string, V2Time?> time, List<string> notes)
    {
        string patientClass = pv1.Value(2).ToUpperInvariant();
        V2Time? start = time(pv1.Value(44)), end = time(pv1.Value(45));
        string status = trigger == "A11" ? "cancelled"
            : end is not null || trigger == "A03" ? "finished"
            : patientClass == "P" ? "planned"
            : patientClass == "U" ? "unknown"
            : "in-progress";
        if (trigger == "A03" && end is null) { notes.Add("A03 without PV1-45: the encounter is finished but has no end time."); }

        JsonObject classCoding;
        if (EncounterClass.TryGetValue(patientClass, out (string Code, string Display) mapped)) { classCoding = Coding("http://terminology.hl7.org/CodeSystem/v3-ActCode", mapped.Code, mapped.Display); }
        else if (OtherPatientClasses.Contains(patientClass)) { classCoding = Coding($"{V2}0004", patientClass); }
        else { throw new MappingException("AE", $"PV1-2 '{pv1.Value(2)}' is not a patient class in table 0004."); }

        JsonObject encounter = new()
        {
            ["resourceType"] = "Encounter",
            ["identifier"] = new JsonArray(new JsonObject
            {
                ["type"] = Concept(Coding($"{V2}0203", "VN", IdentifierType["VN"])), ["system"] = visit.System, ["value"] = visit.Value,
            }),
            ["status"] = status,
            ["class"] = classCoding,
            ["subject"] = Reference(patientUrl),
        };

        string who = string.Join(' ', new[] { pv1.Value(7, 6), pv1.Value(7, 3), pv1.Value(7, 2) }.Where(v => v.Length > 0));
        if (pv1.Value(7).Length > 0 || who.Length > 0)
        {
            JsonObject individual = new();
            if (Key(pv1, 7, 0, pv1.Value(7, 13) is { Length: > 0 } type ? type : "DN", authorityComponent: 9) is ResourceKey doctor)
            {
                individual["identifier"] = new JsonObject { ["system"] = doctor.System, ["value"] = doctor.Value };
            }
            if (who.Length > 0) { individual["display"] = who; }
            encounter["participant"] = new JsonArray(new JsonObject
            {
                ["type"] = new JsonArray(Concept(Coding("http://terminology.hl7.org/CodeSystem/v3-ParticipationType", "ATND", "attender"))),
                ["individual"] = individual,
            });
        }

        JsonObject period = new();
        if (start is not null) { period["start"] = start.Value.Fhir; }
        if (end is not null) { period["end"] = end.Value.Fhir; }
        if (period.Count > 0) { encounter["period"] = period; }

        string where = string.Join(" / ", new[] { pv1.Value(3, 1), pv1.Value(3, 2), pv1.Value(3, 3) }.Where(v => v.Length > 0));
        if (where.Length > 0)
        {
            encounter["location"] = new JsonArray(new JsonObject
            {
                ["location"] = new JsonObject { ["display"] = where },
                ["status"] = patientClass == "P" ? "planned" : status is "finished" or "cancelled" ? "completed" : "active",
            });
        }
        return encounter;
    }

    // ---- AllergyIntolerance --------------------------------------------------------------------------------

    private (JsonObject Resource, string Identifier)? Allergy(Hl7Segment al1, ResourceKey patientKey, string patientUrl, Func<string, V2Time?> time, List<string> notes)
    {
        string code = al1.Value(3, 1), text = al1.Value(3, 2), system = al1.Value(3, 3);
        if (code.Length == 0 && text.Length == 0) { notes.Add("An AL1 with no allergen in AL1-3 was left out."); return null; }

        // AL1 has no identifier of its own. Without one, every resend would create the allergy again, so the
        // identity is derived from what makes the row the same row: the patient and the allergen.
        string identifier = Urn($"allergy|{patientKey}|{system}|{(code.Length > 0 ? code : text.ToUpperInvariant())}");
        JsonObject allergy = new()
        {
            ["resourceType"] = "AllergyIntolerance",
            ["identifier"] = new JsonArray(new JsonObject { ["system"] = UriSystem, ["value"] = identifier }),
            ["clinicalStatus"] = Concept(Coding("http://terminology.hl7.org/CodeSystem/allergyintolerance-clinical", "active", "Active")),
        };
        if (AllergyCategory.TryGetValue(al1.Value(2), out string? category)) { allergy["category"] = new JsonArray(category); }
        else if (al1.Value(2).Length > 0) { notes.Add($"AL1-2 '{al1.Value(2)}' has no FHIR allergy category; none is recorded."); }

        JsonObject concept = new();
        if (code.Length > 0 && CodeSystems.TryGetValue(system, out string? uri)) { concept = Concept(Coding(uri, code, text.Length > 0 ? text : null)); }
        else if (code.Length > 0) { notes.Add($"AL1-3 coding system '{system}' is not configured; the allergen is carried as text."); }
        concept["text"] = text.Length > 0 ? text : code;
        allergy["code"] = concept;
        allergy["patient"] = Reference(patientUrl);
        if (time(al1.Value(6)) is V2Time onset) { allergy["onsetDateTime"] = onset.Fhir; }

        string severity = al1.Value(4), reaction = al1.Value(5);
        if (reaction.Length > 0)
        {
            JsonObject entry = new() { ["manifestation"] = new JsonArray(new JsonObject { ["text"] = reaction }) };
            if (ReactionSeverity.TryGetValue(severity, out string? reactionSeverity)) { entry["severity"] = reactionSeverity; }
            allergy["reaction"] = new JsonArray(entry);
        }
        else if (Criticality.TryGetValue(severity, out string? criticality))
        {
            allergy["criticality"] = criticality;
        }
        return (allergy, identifier);
    }

    // ---- Identifiers and small builders --------------------------------------------------------------------

    private ResourceKey? PatientKey(Hl7Segment segment, int field, List<string> notes)
    {
        List<ResourceKey> records = [];
        for (int r = 0; r < segment.RepetitionCount(field); r++)
        {
            string type = segment.Value(field, 5, 1, r);
            if ((type.Length == 0 || type == "MR") && Key(segment, field, r, "MR") is ResourceKey key) { records.Add(key); }
        }
        if (records.Count > 1) { notes.Add($"{segment.Name}-{field} carries {records.Count} medical record numbers; the first is used to match the patient."); }
        return records.FirstOrDefault();
    }

    /// <summary>Reads a CX or XCN and resolves its system from the assigning authority and identifier type.</summary>
    private ResourceKey? Key(Hl7Segment segment, int field, int repetition, string type, int authorityComponent = 4)
    {
        string value = segment.Value(field, 1, 1, repetition);
        if (value.Length == 0) { return null; }
        string authority = segment.Value(field, authorityComponent, 1, repetition);
        if (options.IdentifierSystems.TryGetValue($"{authority}|{type}", out string? system)) { return new ResourceKey(system, value); }
        // HD.2 and HD.3: a universal ID that says it is an ISO object identifier needs no configuration.
        string universal = segment.Value(field, authorityComponent, 2, repetition);
        return universal.Length > 0 && segment.Value(field, authorityComponent, 3, repetition) == "ISO" ? new ResourceKey($"urn:oid:{universal}", value) : null;
    }

    private static JsonObject Coding(string system, string code, string? display = null)
    {
        JsonObject coding = new() { ["system"] = system, ["code"] = code };
        if (display is not null) { coding["display"] = display; }
        return coding;
    }

    private static JsonObject Concept(JsonObject coding) => new() { ["coding"] = new JsonArray(coding) };
    private static JsonObject Reference(string to) => new() { ["reference"] = to };

    private static JsonObject Entry(string fullUrl, JsonObject resource, string method, string url) => new()
    {
        ["fullUrl"] = fullUrl,
        ["resource"] = resource,
        ["request"] = new JsonObject { ["method"] = method, ["url"] = url },
    };

    private static string Format(TimeSpan offset) => $"{(offset < TimeSpan.Zero ? '-' : '+')}{offset:hh\\:mm}";
    private static string Urn(string name) => $"urn:uuid:{Uuid(name)}";

    /// <summary>A name-based UUID (RFC 4122 version 5): the same name always gives the same UUID.</summary>
    public static string Uuid(string name)
    {
        byte[] hash = SHA1.HashData([.. UuidNamespace.ToByteArray(bigEndian: true), .. Encoding.UTF8.GetBytes(name)]);
        hash[6] = (byte)((hash[6] & 0x0F) | 0x50);
        hash[8] = (byte)((hash[8] & 0x3F) | 0x80);
        return new Guid(hash.AsSpan(0, 16), bigEndian: true).ToString();
    }
}
