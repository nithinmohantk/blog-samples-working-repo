// Runs fixtures/scenario.json through the pipeline. Usage: dotnet run -- <sample root> [bundle-output.json] [schema-output.json]
using System.Text.Json;
using System.Text.Json.Nodes;
using ClinicalCoding.Core;

string root = args.Length > 0 ? args[0] : "../..";
CodingSubset subset = CodingSubset.Load(Path.Combine(root, "terminology", "coding-subset.json"));
JsonNode scenario = JsonNode.Parse(File.ReadAllText(Path.Combine(root, "fixtures", "scenario.json")))!;
int passed = 0, failed = 0;

void Check(string name, bool condition, string detail = "")
{
    if (condition) { passed++; } else { failed++; }
    Console.WriteLine($"{(condition ? "ok  " : "FAIL")}  {name}{(condition ? "" : "  " + detail)}");
}

bool Throws<T>(Action action) where T : Exception
{
    try { action(); return false; } catch (T) { return true; }
}

Decision ToDecision(JsonNode node) => new(node["proposal"]!.GetValue<string>(), node["action"]!.GetValue<string>(), node["code"]?.GetValue<string>());
NoteContext ToNote(JsonNode node) => new(node["patient"]!.GetValue<string>(), node["document"]!.GetValue<string>(), node["date"]!.GetValue<string>(), node["text"]!.GetValue<string>());
Party ToParty(JsonNode node) => new(node["reference"]!.GetValue<string>(), node["display"]!.GetValue<string>());

JsonObject schema = ExtractionSchema.Build(subset);
Check("schema meets the strict structured output limits", ExtractionSchema.Lint(schema).Count == 0, string.Join("; ", ExtractionSchema.Lint(schema)));
JsonObject bad = (JsonObject)schema.DeepClone();
bad["properties"]!["conditions"]!["items"]!["properties"]!["evidence"]!["minLength"] = 1;
((JsonArray)bad["properties"]!["observations"]!["items"]!["required"]!).RemoveAt(3);
Check("schema lint finds an unsupported keyword and an optional property", ExtractionSchema.Lint(bad).Count == 2, string.Join("; ", ExtractionSchema.Lint(bad)));
Check("schema enums are the subset", ((JsonArray)schema["properties"]!["conditions"]!["items"]!["properties"]!["code"]!["enum"]!)
    .Select(n => n!.GetValue<string>()).SequenceEqual([.. subset.Conditions.Select(c => c.Code), "uncoded"]));
string prompt = ExtractionSchema.SystemPrompt(subset);
Check("prompt lists every code", subset.Conditions.All(c => prompt.Contains(c.Code)) && subset.Observations.All(o => prompt.Contains(o.Code)));

Dictionary<string, IReadOnlyList<Proposal>> proposals = [];
foreach ((string name, JsonNode? response) in scenario["responses"]!.AsObject())
{
    NoteContext note = ToNote(scenario["notes"]![response!["note"]!.GetValue<string>()]!);
    proposals[name] = ResponseGuard.Check(ResponseGuard.Parse(response["content"]!.ToJsonString(), subset), note.Text, subset);
    Dictionary<string, string> expected = response["expected"]!.AsObject().ToDictionary(p => p.Key, p => p.Value!.GetValue<string>());
    Check($"guard, {name} response: statuses", proposals[name].Count == expected.Count && proposals[name].All(p => expected[p.Id] == p.Status),
        string.Join(", ", proposals[name].Select(p => $"{p.Id}={p.Status}")));
}

Dictionary<string, Proposal> careless = proposals["careless"].ToDictionary(p => p.Id);
Check("fabricated evidence is blocked", careless["c1"].Reasons.SequenceEqual(["the evidence is not text from the note"]));
Check("a value that differs from the evidence is blocked", careless["o1"].Reasons.SequenceEqual(["the value does not appear in the evidence"]));
Check("an unconverted unit is blocked", careless["o2"].Reasons.SequenceEqual(["only Cel is accepted for this code: enter by hand"]));
Check("an uncoded condition reaches review with a flag", careless["c4"].Code is null && careless["c4"].Flags.Count == 1);
Check("a wrong assertion passes the guard (the reviewer has to catch it)", careless["c5"].Status == ProposalStatus.ForReview);
Check("an implausible value is flagged, not blocked", proposals["implausible"][0].Flags.Count == 1 && proposals["implausible"][1].Flags.Count == 0);

foreach (JsonNode? malformed in scenario["malformed"]!.AsArray())
{
    Check($"malformed response refused: {malformed!["name"]!.GetValue<string>()}",
        Throws<ShapeException>(() => ResponseGuard.Parse(malformed["raw"]!.GetValue<string>(), subset)));
}

JsonNode review = scenario["review"]!;
IReadOnlyList<Proposal> careful = proposals[review["response"]!.GetValue<string>()];
List<Decision> decisions = [.. review["decisions"]!.AsArray().Select(d => ToDecision(d!))];
foreach (JsonNode? refused in review["refused"]!.AsArray())
{
    Check($"review refused: {refused!["name"]!.GetValue<string>()}",
        Throws<ReviewException>(() => ReviewDesk.Apply(careful, [ToDecision(refused["decision"]!)], subset)));
}

Check("review refused: two decisions for one proposal", Throws<ReviewException>(() => ReviewDesk.Apply(careful, [decisions[0], decisions[0]], subset)));
Check("review refused: accepting an uncoded condition", Throws<ReviewException>(() => ReviewDesk.Apply(proposals["careless"], [new Decision("c4", "accept")], subset)));
IReadOnlyList<AcceptedItem> recoded = ReviewDesk.Apply(proposals["careless"], [new Decision("c4", "recode", "49436004"), new Decision("c5", "reject")], subset);
Check("recode gives the subset's display; reject gives nothing", recoded.Count == 1 && recoded[0].Display == "Atrial fibrillation (disorder)");

NoteContext reviewedNote = ToNote(scenario["notes"]![scenario["responses"]![review["response"]!.GetValue<string>()]!["note"]!.GetValue<string>()]!);
ReviewContext context = new(ToParty(review["reviewer"]!), ToParty(review["device"]!), review["at"]!.GetValue<string>());
JsonObject bundle = FhirMapper.ToTransactionBundle(ReviewDesk.Apply(careful, decisions, subset), reviewedNote, context, subset);
List<JsonNode> resources = [.. bundle["entry"]!.AsArray().Select(e => e!["resource"]!)];
int Count(string type) => resources.Count(r => r["resourceType"]!.GetValue<string>() == type);
Check("bundle: 4 conditions, 5 observations, 1 provenance", (Count("Condition"), Count("Observation"), Count("Provenance")) == (4, 5, 1));
Check("bundle: three confirmed, one provisional", resources.Where(r => r["resourceType"]!.GetValue<string>() == "Condition")
    .Select(r => r["verificationStatus"]!["coding"]![0]!["code"]!.GetValue<string>()).SequenceEqual(["confirmed", "confirmed", "confirmed", "provisional"]));
HashSet<string> codes = [.. resources.Where(r => r["code"] is not null).Select(r => r["code"]!["coding"]![0]!["code"]!.GetValue<string>())];
Check("bundle: nothing negated, familial or undecided was written", !codes.Overlaps(["29857009", "386661006", "22298006"]));
Check("bundle: provenance targets every resource and names reviewer and device", resources[^1]["target"]!.AsArray().Count == 9 && resources[^1]["agent"]!.AsArray().Count == 2);
Check("no decisions, no resources", FhirMapper.ToTransactionBundle(ReviewDesk.Apply(careful, [], subset), reviewedNote, context, subset)["entry"]!.AsArray().Count == 0);
Check("same input, same bundle", JsonNode.DeepEquals(bundle, FhirMapper.ToTransactionBundle(ReviewDesk.Apply(careful, decisions, subset), reviewedNote, context, subset)));

JsonSerializerOptions indented = new() { WriteIndented = true };
if (args.Length > 1) { File.WriteAllText(args[1], bundle.ToJsonString(indented)); }
if (args.Length > 2) { File.WriteAllText(args[2], schema.ToJsonString(indented)); }
Console.WriteLine($"\n{passed} of {passed + failed} checks passed");
return failed == 0 ? 0 : 1;
