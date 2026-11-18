// Self-checking console test. Synthetic data only. Run: dotnet run
using System.Text.Json;
using System.Text.Json.Nodes;
using Interop;

static void Check(bool condition, string what)
{
    if (!condition)
    {
        throw new InvalidOperationException($"FAILED: {what}");
    }
}

JsonNode Load(string file) => JsonNode.Parse(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, file)))!;

Dictionary<string, string> patientIndex = new() { ["ehr-aaa"] = "pat-001" };
(JsonObject bundle, MappingReport report) =
    MedicationOrderMapper.ToBundle(Load("medication_orders.json"), Load("medication_actions.json"), patientIndex);

Console.WriteLine($"mapped rows      -> {report.MappedRows}");
Console.WriteLine($"rejected         -> {string.Join("; ", report.Rejected)}");
Console.WriteLine($"unmapped columns -> {string.Join("; ", report.UnmappedColumns)}");
report.Notes.ForEach(n => Console.WriteLine($"note             -> {n}"));

Dictionary<string, string> statuses = bundle["entry"]!.AsArray().ToDictionary(
    e => ((string)e!["resource"]!["identifier"]![0]!["value"]!).Split(':')[^1],
    e => (string)e!["resource"]!["status"]!);

Check(report.MappedRows == 4 && bundle["entry"]!.AsArray().Count == 4, "four resources");
Check(statuses["ORD-1001"] == "active" && statuses["ORD-1002"] == "completed"
      && statuses["ORD-1003"] == "stopped" && statuses["ORD-1004"] == "unknown", "statuses from latest ACTION");
Check(report.Rejected.SequenceEqual(
    ["ORD-2001: no FHIR Patient for EHR ehr-zzz", "ORD-1005: missing required medication"]), "rejections");
Check(report.UnmappedColumns.SequenceEqual(["dosage_justification"]), "unmapped columns");

JsonNode first = bundle["entry"]![0]!;
Check((string)first["request"]!["url"]! ==
      "MedicationRequest?identifier=urn%3Aopenehr%3Amedication-order%7C"
      + "11111111-0000-4000-8000-000000000001%3A%3Asynthetic.example%3AORD-1001", "conditional update URL");
Check(first["resource"]!["medicationCodeableConcept"]!["coding"] is null, "local formulary code not exported");
Check((string)first["resource"]!["dosageInstruction"]![0]!["route"]!["coding"]![0]!["code"]! == "26643006", "route");

JsonObject probe = [];
MedicationOrderMapper.SetPath(probe, "a[1].b.c", JsonValue.Create(1));
Check(probe.ToJsonString() == """{"a":[{},{"b":{"c":1}}]}""", "SetPath");

string output = Path.Combine(Environment.CurrentDirectory, "bundle.dotnet.json");
File.WriteAllText(output, bundle.ToJsonString(new JsonSerializerOptions { WriteIndented = true }));
Console.WriteLine("ALL AQL-TO-FHIR TESTS OK (.NET " + Environment.Version + ")");
