// dotnet run -c Release -- <messages dir> <output dir>                       reader, times, mapping, acknowledgements
// dotnet run -c Release -- <messages dir> <output dir> http://host/fhir      also applies the messages to a FHIR R4 server
using System.Text.Json;
using System.Text.Json.Nodes;
using AdtToFhir.Core;

int passed = 0, failed = 0;
void Check(string name, bool condition, string detail = "")
{
    if (condition) { passed++; } else { failed++; }
    Console.WriteLine($"{(condition ? "ok  " : "FAIL")}  {name}{(condition || detail.Length == 0 ? "" : $"  [{detail}]")}");
}

string messagesDir = args[0], outDir = args[1];
string? fhirBase = args.Length > 2 ? args[2].TrimEnd('/') + "/" : null;
Directory.CreateDirectory(Path.Combine(outDir, "mapped"));
Directory.CreateDirectory(Path.Combine(outDir, "naive"));
Directory.CreateDirectory(Path.Combine(outDir, "sent"));
string Read(string file) => File.ReadAllText(Path.Combine(messagesDir, file));
void Save(string folder, string name, JsonNode node) => File.WriteAllText(Path.Combine(outDir, folder, name), node.ToJsonString(FhirJson.Indented) + "\n");

const string Mrn = "urn:oid:2.999.1.1", Visit = "urn:oid:2.999.1.2";
MapperOptions options = new()
{
    // 2.999 is the OID arc reserved for examples. A real interface lists its senders' authorities here.
    IdentifierSystems = new Dictionary<string, string>
    {
        ["GENHOSP|MR"] = Mrn, ["GENHOSP|VN"] = Visit, ["GENHOSP|DN"] = "urn:oid:2.999.1.3", ["GENHOSP|MSG"] = "urn:oid:2.999.1.9", ["REGION|PI"] = "urn:oid:2.999.2.1",
    },
    DefaultOffset = TimeSpan.Zero,
};
AdtMapper mapper = new(options);
DateTimeOffset received = new(2026, 3, 14, 9, 0, 0, TimeSpan.Zero);
MapResult Map(string text) => mapper.Map(Hl7Message.Parse(text), received);
string? Refusal(string text)
{
    try { Map(text); return null; }
    catch (MappingException error) { return error.AckCode; }
}
JsonObject Resource(MapResult result, string type, int index = 0) =>
    result.Bundle["entry"]!.AsArray().Select(e => e!["resource"]!.AsObject()).Where(r => r["resourceType"]!.GetValue<string>() == type).ElementAt(index);
int Count(MapResult result, string type) => result.Bundle["entry"]!.AsArray().Count(e => e!["resource"]!["resourceType"]!.GetValue<string>() == type);
string S(JsonNode? node) => node?.GetValue<string>() ?? "";

// ---- 1. The reader -----------------------------------------------------------------------------------------
Console.WriteLine("== reader");
Hl7Message admit = Hl7Message.Parse(Read("01-a01-admit.hl7"));
Hl7Segment pid = admit.First("PID")!;
Check("an A01 is read as seven segments with its type, trigger and control ID", admit.Segments.Count == 7 && admit.MessageCode == "ADT" && admit.TriggerEvent == "A01" && admit.ControlId == "MSG00001");
Check("PID-3 has two repetitions, each with its own authority and type", pid.RepetitionCount(3) == 2 && pid.Value(3, 4, 1, 0) == "GENHOSP" && pid.Value(3, 5, 1, 1) == "PI");
Check(@"\T\ in an address comes out as an ampersand", pid.Value(11, 1) == "Flat 2, Smith & Sons Building", pid.Value(11, 1));
Hl7Segment escapes = Hl7Message.Parse("MSH|^~\\&|A|B|C|D|20260310||ADT^A08|E1|P|2.5.1\rNTE|1|a\\F\\b\\S\\c\\R\\d\\E\\e|caf\\XC3A9\\|one\\.br\\two|\\H\\bold\\N\\|50\\").First("NTE")!;
Check(@"\F\ \S\ \R\ \E\ give back the four delimiter characters", escapes.Value(2) == @"a|b^c~d\e", escapes.Value(2));
Check(@"\X..\ hexadecimal data is decoded as UTF-8", escapes.Value(3) == "café", escapes.Value(3));
Check(@"\.br\ becomes a line break and highlighting escapes are dropped", escapes.Value(4) == "one\ntwo" && escapes.Value(5) == "bold");
Check("a lone escape character is kept as sent", escapes.Value(6) == @"50\", escapes.Value(6));
Hl7Message custom = Hl7Message.Parse("MSH#*!$@#APP#FAC#RCV#RFAC#20260310##ADT*A08#C1#P#2.5.1\rPID###123***AUTH*MR!456***AUTH*PI##Smith $S$ Jones*Ann");
Check("delimiters are taken from MSH-1 and MSH-2, not assumed", custom.TriggerEvent == "A08" && custom.First("PID")!.Value(3, 5, 1, 1) == "PI" && custom.First("PID")!.Value(5, 1) == "Smith * Jones");
Check("an MLLP frame around the message is ignored", Hl7Message.Parse("\u000B" + Read("01-a01-admit.hl7").Replace("\n", "\r") + "\u001C\r").Segments.Count == 7);
Hl7Segment older = Hl7Message.Parse(Read("08-a04-older-sender.hl7")).First("PID")!;
Check("two double quotes are an explicit null, not a value", older.IsExplicitNull(13) && older.Value(13) == "" && older.RepetitionCount(13) == 0);
string[] unreadable = ["PID|1||700001", "MSH|^^\\&|A|B|C|D|20260310||ADT^A01|X|P|2.5.1", "MSH|^~\\&|A|B|C|D|20260310||ADT^A01||P|2.5.1", "MSH|^~\\&|A|B|C|D|20260310||ADT^A01|X|P|2.5.1\rthis is not a segment"];
Check("four unreadable inputs are refused: no MSH, repeated delimiter, no control ID, a line that is not a segment", unreadable.All(text =>
{
    try { Hl7Message.Parse(text); return false; }
    catch (Hl7ParseException) { return true; }
}));

// ---- 2. Dates and times ------------------------------------------------------------------------------------
Console.WriteLine("== dates and times");
(string V2, TimeSpan? Default, string? Fhir)[] times =
[
    ("1985", null, "1985"), ("198503", null, "1985-03"), ("19850312", null, "1985-03-12"),
    ("20260310081500+0000", null, "2026-03-10T08:15:00+00:00"), ("202603100815+0100", null, "2026-03-10T08:15:00+01:00"),
    ("20260310081500.1234-0500", null, "2026-03-10T08:15:00-05:00"), ("20260310081500", TimeSpan.Zero, "2026-03-10T08:15:00+00:00"),
    ("20260310081500", null, "2026-03-10"), ("20260230", null, null), ("2026031025", TimeSpan.Zero, null), ("10/03/2026", null, null), ("", null, null),
];
foreach ((string v2, TimeSpan? fallback, string? fhir) in times)
{
    string? actual = V2Time.Parse(v2, fallback)?.Fhir;
    Console.WriteLine($"  {(v2.Length == 0 ? "(empty)" : v2),-26} {(fallback is null ? "no default offset" : "default +00:00"),-18} -> {actual ?? "(not a time)"}");
    if (actual != fhir) { Check($"time '{v2}'", false, $"expected {fhir ?? "null"}"); }
}
Check("twelve dates and times convert at the precision given, and impossible ones are refused", times.All(t => V2Time.Parse(t.V2, t.Default)?.Fhir == t.Fhir));
Check("a time with no offset is marked as assumed when the default is used", V2Time.Parse("20260310081500", TimeSpan.Zero)!.Value.OffsetAssumed && !V2Time.Parse("20260310081500+0000", TimeSpan.Zero)!.Value.OffsetAssumed);

// ---- 3. The mapping ----------------------------------------------------------------------------------------
Console.WriteLine("== mapping");
Dictionary<string, MapResult> mapped = [];
foreach (string file in Directory.GetFiles(messagesDir, "*.hl7").Select(Path.GetFileName).Order()!)
{
    try
    {
        mapped[file] = Map(Read(file));
        Save("mapped", Path.ChangeExtension(file, ".json"), mapped[file].Bundle);
        Console.WriteLine($"  {file,-34} {string.Join(", ", mapped[file].Bundle["entry"]!.AsArray().Select(e => S(e!["resource"]!["resourceType"])))}");
        foreach (string note in mapped[file].Notes) { Console.WriteLine($"      note: {note}"); }
    }
    catch (MappingException error) { Console.WriteLine($"  {file,-34} {error.AckCode}: {error.Message}"); }
}

MapResult a01 = mapped["01-a01-admit.hl7"];
JsonObject patient = Resource(a01, "Patient"), encounter = Resource(a01, "Encounter");
JsonArray requests = [.. a01.Bundle["entry"]!.AsArray().Select(e => (JsonNode)$"{S(e!["request"]!["method"])} {S(e["request"]!["url"])}")];
Check("A01 gives Patient, Encounter, two AllergyIntolerance and Provenance, with no notes", Count(a01, "Patient") == 1 && Count(a01, "Encounter") == 1 && Count(a01, "AllergyIntolerance") == 2 && Count(a01, "Provenance") == 1 && a01.Notes.Count == 0);
Check("the Patient is written by its record number, not by a server id", S(requests[0]) == "PUT Patient?identifier=urn%3Aoid%3A2.999.1.1%7C700001", S(requests[0]));
Check("the Encounter is written by its visit number", S(requests[1]) == "PUT Encounter?identifier=urn%3Aoid%3A2.999.1.2%7CV9001", S(requests[1]));
Check("both identifiers carry a system resolved from authority and type", patient["identifier"]!.AsArray().Select(i => $"{S(i!["system"])}|{S(i["value"])}").SequenceEqual([$"{Mrn}|700001", "urn:oid:2.999.2.1|PT-55-0193"]));
Check("legal and maiden names keep their use; middle name and prefix are kept", S(patient["name"]![0]!["use"]) == "official" && S(patient["name"]![0]!["family"]) == "O'Brien" && patient["name"]![0]!["given"]!.AsArray().Count == 2 && S(patient["name"]![0]!["prefix"]![0]) == "Ms" && S(patient["name"]![1]!["use"]) == "maiden");
Check("sex F becomes gender female and the birth date is a FHIR date", S(patient["gender"]) == "female" && S(patient["birthDate"]) == "1985-03-12");
Check("home telephone, email and work telephone are told apart", patient["telecom"]!.AsArray().Select(t => $"{S(t!["system"])}/{S(t["use"])}").SequenceEqual(["phone/home", "email/home", "phone/work"]));
Check("the address keeps its two lines, with the escape resolved", S(patient["address"]![0]!["line"]![0]) == "Flat 2, Smith & Sons Building" && S(patient["address"]![0]!["line"]![1]) == "14 Example Street" && S(patient["address"]![0]!["use"]) == "home");
Check("NK1 becomes a contact with its role and its relationship", S(patient["contact"]![0]!["relationship"]![0]!["coding"]![0]!["code"]) == "C" && S(patient["contact"]![0]!["relationship"]![1]!["coding"]![0]!["code"]) == "SPO" && S(patient["contact"]![0]!["telecom"]![0]!["use"]) == "mobile");
Check("patient class I becomes an in-progress inpatient encounter", S(encounter["status"]) == "in-progress" && S(encounter["class"]!["code"]) == "IMP" && S(encounter["period"]!["start"]) == "2026-03-10T08:00:00+00:00");
Check("the encounter points at the patient in the same Bundle", S(encounter["subject"]!["reference"]) == S(a01.Bundle["entry"]![0]!["fullUrl"]));
Check("location and attending doctor are carried without inventing resources", S(encounter["location"]![0]!["location"]!["display"]) == "W4 / R12 / B" && S(encounter["participant"]![0]!["individual"]!["display"]) == "Dr Niamh Murphy" && S(encounter["participant"]![0]!["individual"]!["identifier"]!["system"]) == "urn:oid:2.999.1.3");
JsonObject penicillin = Resource(a01, "AllergyIntolerance"), peanut = Resource(a01, "AllergyIntolerance", 1);
Check("a reaction with a severity goes to reaction.severity; a severity alone goes to criticality", S(penicillin["reaction"]![0]!["severity"]) == "severe" && S(penicillin["reaction"]![0]!["manifestation"]![0]!["text"]) == "Rash" && S(peanut["criticality"]) == "low" && peanut["reaction"] is null);
Check("each allergy has an identifier derived from patient and allergen", S(penicillin["identifier"]![0]!["value"]).StartsWith("urn:uuid:") && S(penicillin["identifier"]![0]!["value"]) != S(peanut["identifier"]![0]!["value"]));
Check("the same message maps to the same Bundle, byte for byte", Map(Read("01-a01-admit.hl7")).Bundle.ToJsonString() == a01.Bundle.ToJsonString());
Check("the Provenance id depends on the control ID", a01.ProvenanceId == Map(Read("01-a01-admit.hl7")).ProvenanceId && a01.ProvenanceId != Map(Read("01-a01-admit.hl7").Replace("MSG00001", "MSG0000X")).ProvenanceId);

MapResult a08 = mapped["02-a08-update.hl7"], a03 = mapped["03-a03-discharge.hl7"], a11 = mapped["05-a11-cancel-admit.hl7"], a40 = mapped["06-a40-merge.hl7"], a04 = mapped["08-a04-older-sender.hl7"];
Check("A08 updates the patient and allergies and leaves the encounter alone, with a note", Count(a08, "Encounter") == 0 && Count(a08, "AllergyIntolerance") == 3 && a08.Notes.Any(n => n.StartsWith("PV1 is not applied")));
Check("an allergen from an unconfigured coding system is kept as text, with a note", Resource(a08, "AllergyIntolerance", 2)["code"]!["coding"] is null && S(Resource(a08, "AllergyIntolerance", 2)["code"]!["text"]) == "Latex" && a08.Notes.Any(n => n.Contains("99LOCAL")));
Check("A03 finishes the encounter at PV1-45 and orders by EVN-6", S(Resource(a03, "Encounter")["status"]) == "finished" && S(Resource(a03, "Encounter")["period"]!["end"]) == "2026-03-12T13:30:00+00:00" && a03.EventTime == new DateTimeOffset(2026, 3, 12, 13, 30, 0, TimeSpan.Zero));
Check("A11 cancels the encounter", S(Resource(a11, "Encounter")["status"]) == "cancelled" && S(Resource(a11, "Encounter")["class"]!["code"]) == "EMER");
Check("a full PID speaks for every part of the patient; a sparse one only for what it sent or withdrew", a01.Replaces.SequenceEqual(["name", "birthDate", "gender", "address", "telecom:home", "telecom:work", "maritalStatus", "contact"])
    && mapped["12-a08-sparse-update.hl7"].Replaces.SequenceEqual(["name", "address", "telecom:home"]) && Resource(mapped["12-a08-sparse-update.hl7"], "Patient")["address"] is null, string.Join(",", mapped["12-a08-sparse-update.hl7"].Replaces));
Check("A40 names the surviving and the retired record", a40.Patient.Value == "700001" && a40.PriorPatient?.Value == "700002" && Count(a40, "Encounter") == 0);

JsonObject tom = Resource(a04, "Patient");
Check("a v2.3.1 A04 with no offsets maps, using the configured offset and saying so", S(Resource(a04, "Encounter")["period"]!["start"]) == "2026-03-13T10:00:00+00:00" && S(Resource(a04, "Encounter")["class"]!["code"]) == "AMB" && a04.Notes.Any(n => n.Contains("was assumed")));
Check("a month-precision birth date stays month-precision", S(tom["birthDate"]) == "1980-11");
Check("an unknown sex code becomes gender unknown, with a note", S(tom["gender"]) == "unknown" && a04.Notes.Any(n => n.StartsWith("PID-8")));
Check("marital code A (separated in v2) is not passed off as A (annulled in FHIR)", tom["maritalStatus"]!["coding"] is null && S(tom["maritalStatus"]!["text"]) == "Separated");
Check(@"\F\ in a street line gives a vertical bar; an explicit null gives no telecom", S(tom["address"]![0]!["line"]![0]) == "3 Test Lane | Rear Annex" && tom["telecom"] is null);
Check("a contact with no name or telephone, an unmapped allergen type and a Z-segment are each reported", tom["contact"] is null && a04.Notes.Any(n => n.StartsWith("An NK1")) && a04.Notes.Any(n => n.StartsWith("AL1-2")) && a04.Notes.Any(n => n.StartsWith("Segment ZPD")));

string admitText = Read("01-a01-admit.hl7");
Check("an A02 transfer is rejected (AR): this interface does not convert it", Refusal(Read("09-a02-transfer.hl7")) == "AR");
Check("a patient with no record number is an error (AE)", Refusal(Read("10-a01-no-record-number.hl7")) == "AE");
Check("an unknown assigning authority is an error (AE), not a guess", Refusal(admitText.Replace("700001^^^GENHOSP^MR", "700001^^^OTHERHOSP^MR")) == "AE");
Check("an authority given as an ISO object identifier needs no configuration", Map(admitText.Replace("700001^^^GENHOSP^MR", "700001^^^&2.999.7.7&ISO^MR")).Patient.System == "urn:oid:2.999.7.7");
Check("an admission with no visit number, or a patient class outside table 0004, is an error (AE)", Refusal(admitText.Replace("V9001^^^GENHOSP^VN", "")) == "AE" && Refusal(admitText.Replace("PV1|1|I|", "PV1|1|Q|")) == "AE");
Check("a merge of a record into itself is an error (AE)", Refusal(Read("06-a40-merge.hl7").Replace("MRG|700002", "MRG|700001")) == "AE");

// ---- 4. Acknowledgements -----------------------------------------------------------------------------------
Console.WriteLine("== acknowledgements");
string ack = Ack.Build(admit, "AE", "PID-3 | is empty", received);
Console.WriteLine("  " + ack.Replace("\r", "\n  ").TrimEnd());
Hl7Message ackRead = Hl7Message.Parse(ack);
Check("the acknowledgement swaps sender and receiver and returns the control ID", ackRead.First("MSH")!.Value(3) == "FHIRGW" && ackRead.First("MSH")!.Value(5) == "ADTSYS" && ackRead.MessageCode == "ACK" && ackRead.First("MSA")!.Value(2) == "MSG00001");
Check("free text in MSA-3 is escaped and reads back unchanged", ack.Contains(@"PID-3 \F\ is empty") && ackRead.First("MSA")!.Value(3) == "PID-3 | is empty");

// ---- 5. What a first attempt looks like: v2 values copied across unchanged ----------------------------------
JsonObject naivePatient = new()
{
    ["resourceType"] = "Patient",
    ["identifier"] = new JsonArray(new JsonObject { ["system"] = "GENHOSP", ["value"] = pid.Value(3) }),
    ["name"] = new JsonArray(new JsonObject { ["family"] = pid.Value(5, 1), ["given"] = new JsonArray(pid.Value(5, 2)) }),
    ["gender"] = pid.Value(8),
    ["birthDate"] = pid.Value(7),
};
Hl7Segment pv1 = admit.First("PV1")!;
JsonObject naiveEncounter = new()
{
    ["resourceType"] = "Encounter",
    ["status"] = "in-progress",
    ["class"] = new JsonObject { ["system"] = "http://terminology.hl7.org/CodeSystem/v3-ActCode", ["code"] = pv1.Value(2) },
    ["subject"] = new JsonObject { ["display"] = "O'Brien, Aoife" },
    ["period"] = new JsonObject { ["start"] = pv1.Value(44) },
};
Save("naive", "patient.json", naivePatient);
Save("naive", "encounter.json", naiveEncounter);

// ---- 6. The same messages through a FHIR server ------------------------------------------------------------
if (fhirBase is not null)
{
    Console.WriteLine($"== against {fhirBase}");
    using HttpClient http = new() { BaseAddress = new Uri(fhirBase), Timeout = TimeSpan.FromSeconds(120) };
    FhirApplier applier = new(http);
    AdtPipeline pipeline = new(mapper, applier, TimeProvider.System);
    int step = 0;
    async Task<ProcessResult> Send(string label, string text, string expectAck, ApplyOutcome? expectOutcome)
    {
        ProcessResult result = await pipeline.ProcessAsync(text);
        step++;
        if (result.Sent is not null) { Save("sent", $"{step:00}-{label}.json", result.Sent); }
        Check($"{step,2}. {label}: {expectAck}{(expectOutcome is null ? "" : $", {expectOutcome}")}", result.AckCode == expectAck && result.Outcome == expectOutcome, $"{result.AckCode} {result.Outcome} {result.Detail}");
        if (result.Detail.Length > 0) { Console.WriteLine($"        {result.Detail}"); }
        return result;
    }
    async Task<JsonObject> Get(string url)
    {
        using HttpRequestMessage request = new(HttpMethod.Get, url);
        request.Headers.TryAddWithoutValidation("Cache-Control", "no-cache");
        using HttpResponseMessage response = await http.SendAsync(request);
        return JsonNode.Parse(await response.Content.ReadAsStringAsync())!.AsObject();
    }
    async Task<List<JsonObject>> Search(string url) => [.. ((await Get(url))["entry"]?.AsArray() ?? []).Select(e => e!["resource"]!.AsObject())];
    string Escape(string system, string value) => Uri.EscapeDataString($"{system}|{value}");

    await Send("a01-admit", Read("01-a01-admit.hl7"), "AA", ApplyOutcome.Applied);
    await Send("a01-admit-sent-again", Read("01-a01-admit.hl7"), "AA", ApplyOutcome.Duplicate);
    await Send("a08-update", Read("02-a08-update.hl7"), "AA", ApplyOutcome.Applied);
    await Send("a03-discharge", Read("03-a03-discharge.hl7"), "AA", ApplyOutcome.Applied);
    JsonObject afterDischarge = (await Search($"Patient?identifier={Escape(Mrn, "700001")}"))[0], stayAfterDischarge = (await Search($"Encounter?identifier={Escape(Visit, "V9001")}"))[0];
    Check("    the discharge carried no NK1, and the emergency contact is still on the patient", S(afterDischarge["contact"]?[0]?["name"]?["family"]) == "O'Brien" && afterDischarge["identifier"]!.AsArray().Count == 2);
    Check("    the discharge added an end to the stay and kept its start, location and doctor", S(stayAfterDischarge["period"]!["start"]) == "2026-03-10T08:00:00+00:00" && S(stayAfterDischarge["period"]!["end"]) == "2026-03-12T13:30:00+00:00" && stayAfterDischarge["participant"] is not null && S(stayAfterDischarge["meta"]!["versionId"]) == "2");
    await Send("a08-update-arriving-late", Read("02-a08-update.hl7").Replace("MSG00002", "MSG00002-LATE"), "AA", ApplyOutcome.Stale);
    await Send("a01-second-registration", Read("04-a01-second-registration.hl7"), "AA", ApplyOutcome.Applied);
    await Send("a11-cancel-admit", Read("05-a11-cancel-admit.hl7"), "AA", ApplyOutcome.Applied);
    await Send("a40-merge", Read("06-a40-merge.hl7"), "AA", ApplyOutcome.Applied);
    await Send("a08-to-retired-record", Read("07-a08-to-retired-record.hl7"), "AE", ApplyOutcome.PatientMerged);
    await Send("a08-after-merge", Read("11-a08-after-merge.hl7"), "AA", ApplyOutcome.Applied);
    ProcessResult olderSender = await Send("a04-older-sender", Read("08-a04-older-sender.hl7"), "AA", ApplyOutcome.Applied);
    await Send("a02-transfer", Read("09-a02-transfer.hl7"), "AR", null);
    await Send("a01-no-record-number", Read("10-a01-no-record-number.hl7"), "AE", null);

    // Two writers on one patient: the first reads, the second reads and writes, then the first tries to write.
    string later = Read("11-a08-after-merge.hl7");
    MapResult first = Map(later.Replace("MSG00011", "MSG00012").Replace("20260314090000", "20260314100000"));
    Prepared held = await applier.PrepareAsync(first);
    await Send("a08-second-writer", later.Replace("MSG00011", "MSG00013").Replace("20260314090000", "20260314100500").Replace("0155", "0156"), "AA", ApplyOutcome.Applied);
    ApplyResult collided = await applier.SendAsync(held);
    step++;
    Check($"{step,2}. a write prepared before another writer's update is refused by the server", collided.Outcome == ApplyOutcome.Conflict, $"{collided.Outcome} {collided.Detail}");
    Console.WriteLine($"        {collided.Detail}");
    await Send("a08-first-writer-retried", later.Replace("MSG00011", "MSG00012").Replace("20260314090000", "20260314100000"), "AA", ApplyOutcome.Stale);
    await Send("a40-merge-of-a-record-never-seen", later.Replace("MSG00011", "MSG00014").Replace("20260314090000", "20260314110000").Replace("A08", "A40") + "MRG|700009^^^GENHOSP^MR\n", "AA", ApplyOutcome.Applied);


    // An update that changes nothing in the Patient: is a new version written?
    string versionBefore = S((await Search($"Patient?identifier={Escape(Mrn, "700001")}"))[0]["meta"]!["versionId"]);
    await Send("a08-with-nothing-new", later.Replace("MSG00011", "MSG00015").Replace("20260314090000", "20260314120000"), "AA", ApplyOutcome.Applied);
    string versionAfter = S((await Search($"Patient?identifier={Escape(Mrn, "700001")}"))[0]["meta"]!["versionId"]);
    Console.WriteLine($"        Patient version before {versionBefore}, after {versionAfter}");
    Check("    an update that changes nothing writes no new Patient version", versionBefore == versionAfter, $"{versionBefore} -> {versionAfter}");

    await Send("a08-sparse-update", Read("12-a08-sparse-update.hl7"), "AA", ApplyOutcome.Applied);
    JsonObject tomNow = (await Search($"Patient?identifier={Escape(Mrn, "700003")}"))[0];
    Check("    a sparse update kept the birth date, gender and marital status it did not mention", S(tomNow["birthDate"]) == "1980-11" && S(tomNow["gender"]) == "unknown" && S(tomNow["maritalStatus"]!["text"]) == "Separated");
    Check("    it removed the address sent as an explicit null and added the telephone", tomNow["address"] is null && S(tomNow["telecom"]![0]!["value"]).EndsWith("0188"));

    // Reported, not asserted: does this server accept an absolute reference to one of its own resources in a transaction?
    string stubId = S((await Search($"Patient?identifier={Escape(Mrn, "700009")}"))[0]["id"]);
    JsonObject absolute = new()
    {
        ["resourceType"] = "Bundle", ["type"] = "transaction",
        ["entry"] = new JsonArray(new JsonObject
        {
            ["fullUrl"] = $"urn:uuid:{AdtMapper.Uuid("experiment")}",
            ["resource"] = new JsonObject { ["resourceType"] = "List", ["status"] = "current", ["mode"] = "working", ["subject"] = new JsonObject { ["reference"] = $"{fhirBase}Patient/{stubId}" } },
            ["request"] = new JsonObject { ["method"] = "POST", ["url"] = "List" },
        }),
    };
    ApplyResult experiment = await applier.SendAsync(new Prepared(null, "", absolute));
    string stored = experiment.Outcome == ApplyOutcome.Applied ? S((await Search("List?_count=1"))[0]["subject"]!["reference"]) : "";
    Console.WriteLine($"  experiment, absolute reference to a local resource: {experiment.Outcome} {experiment.Detail}{(stored.Length > 0 ? $"stored as {stored}" : "")}");

    Console.WriteLine("== what the server holds");
    List<JsonObject> survivors = await Search($"Patient?identifier={Escape(Mrn, "700001")}"), retired = await Search($"Patient?identifier={Escape(Mrn, "700002")}"), stub = await Search($"Patient?identifier={Escape(Mrn, "700009")}");
    Check("one Patient per record number after every message", survivors.Count == 1 && retired.Count == 1 && stub.Count == 1, $"{survivors.Count} {retired.Count} {stub.Count}");
    JsonObject aoife = survivors[0], duplicate = retired[0];
    string aoifeId = S(aoife["id"]), duplicateId = S(duplicate["id"]);
    Console.WriteLine($"  Patient/{aoifeId} is version {S(aoife["meta"]!["versionId"])}; Patient/{duplicateId} is version {S(duplicate["meta"]!["versionId"])}");
    Check("the surviving record has the latest address and telephone", S(aoife["address"]![0]!["line"]![0]) == "9 Sample Road" && aoife["telecom"]!.AsArray().Any(t => S(t!["value"]).EndsWith("0155")));
    List<string> links = [.. (aoife["link"]?.AsArray() ?? []).Select(l => $"{S(l!["type"])} {S(l["other"]!["reference"])}")];
    Check("it replaces both retired records, and the links survived two later updates", links.Contains($"replaces Patient/{duplicateId}") && links.Contains($"replaces Patient/{S(stub[0]["id"])}") && links.Count == 2, string.Join("; ", links));
    Check("the retired record is inactive, points at the survivor and kept its own details", duplicate["active"]!.GetValue<bool>() == false && S(duplicate["link"]![0]!["type"]) == "replaced-by" && S(duplicate["link"]![0]!["other"]!["reference"]) == $"Patient/{aoifeId}" && S(duplicate["name"]![0]!["family"]) == "OBrien" && duplicate["telecom"] is null);
    Check("a record that was never received exists as an inactive stub", stub[0]["active"]!.GetValue<bool>() == false && S(stub[0]["link"]![0]!["other"]!["reference"]) == $"Patient/{aoifeId}" && stub[0]["name"] is null);

    List<JsonObject> stay = await Search($"Encounter?identifier={Escape(Visit, "V9001")}"), cancelled = await Search($"Encounter?identifier={Escape(Visit, "V9002")}");
    Check("the inpatient stay is finished and was not reopened by the late update", stay.Count == 1 && S(stay[0]["status"]) == "finished" && S(stay[0]["period"]!["end"]) == "2026-03-12T13:30:00+00:00" && S(stay[0]["subject"]!["reference"]) == $"Patient/{aoifeId}");
    Check("the cancelled visit is cancelled", cancelled.Count == 1 && S(cancelled[0]["status"]) == "cancelled");
    string cancelledSubject = S(cancelled[0]["subject"]!["reference"]);
    Console.WriteLine($"  the cancelled visit still refers to {cancelledSubject}, the retired record: a merge here links records and does not move their data");
    Check("the merge did not move the retired record's encounter", cancelledSubject == $"Patient/{duplicateId}");

    List<JsonObject> allergies = await Search($"AllergyIntolerance?patient=Patient/{aoifeId}&_count=50");
    Check("three allergies after five messages that carried them: no duplicates", allergies.Count == 3, $"{allergies.Count}");
    List<JsonObject> history = await Search($"Provenance?target=Patient/{aoifeId}&_sort=when&_count=50");
    Console.WriteLine($"  events applied to Patient/{aoifeId}: {string.Join(", ", history.Select(p => $"{S(p["activity"]!["coding"]![0]!["code"])} {S(p["occurredDateTime"])[..16]}"))}");
    Check("eight Provenance records, in event order, and none for the two messages that were not applied", history.Count == 8 && history.Select(p => S(p["entity"]![0]!["what"]!["identifier"]!["value"])).SequenceEqual(["MSG00001", "MSG00002", "MSG00003", "MSG00006", "MSG00011", "MSG00013", "MSG00014", "MSG00015"]),
        string.Join(",", history.Select(p => S(p["entity"]![0]!["what"]!["identifier"]!["value"]))));
    Check("the notes of the awkward message travelled with its result", olderSender.Notes.Count >= 5, $"{olderSender.Notes.Count}");

    File.WriteAllText(Path.Combine(outDir, "ids.json"), JsonSerializer.Serialize(new { @base = fhirBase, mrnSystem = Mrn, visitSystem = Visit, survivor = aoifeId, retired = duplicateId, stub = S(stub[0]["id"]) }) + "\n");
}

Console.WriteLine($"\n{passed} of {passed + failed} checks passed");
return failed == 0 ? 0 : 1;
