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

string json = await File.ReadAllTextAsync(Path.Combine(AppContext.BaseDirectory, "bp_composition.json"));
JsonNode composition = JsonNode.Parse(json)!;

MappingResult result = BloodPressureMapper.ToFhir(composition, "pat-001");
JsonObject observation = result.Observations[0];
Console.WriteLine(observation.ToJsonString(new JsonSerializerOptions { WriteIndented = true }));
Console.WriteLine($"mapped      -> {string.Join("; ", result.Mapped)}");
Console.WriteLine($"not carried -> {string.Join("; ", result.NotCarried)}");

Dictionary<string, decimal> values = observation["component"]!.AsArray().ToDictionary(
    c => (string)c!["code"]!["coding"]![0]!["code"]!,
    c => c!["valueQuantity"]!["value"]!.GetValue<decimal>());

Check(result.Observations.Count == 1, "one observation per event");
Check(values["8480-6"] == 142 && values["8462-4"] == 88, "systolic and diastolic values");
Check((string)observation["effectiveDateTime"]! == "2026-08-03T09:42:00+00:00", "effective time");
Check((string)observation["subject"]!["reference"]! == "Patient/pat-001", "subject");
Check(((string)observation["identifier"]![0]!["value"]!).StartsWith("8f2c1a9e"), "provenance identifier");
Check((string)observation["bodySite"]!["coding"]![0]!["code"]! == "368209003", "body site");
Check(result.NotCarried.SequenceEqual(["state/Position = Sitting", "protocol/Cuff size = Large Adult"]),
    "loss report");

JsonNode bad = JsonNode.Parse(json)!;
bad["content"]![0]!["data"]!["events"]![0]!["data"]!["items"]![0]!["value"]!["units"] = "kPa";
try
{
    BloodPressureMapper.ToFhir(bad, "pat-001");
    Check(false, "kPa must be rejected");
}
catch (InvalidOperationException ex) when (ex.Message.Contains("expected mm[Hg]"))
{
    Console.WriteLine($"unit check  -> {ex.Message}");
}

Console.WriteLine("ALL BP MAPPING TESTS OK (.NET " + Environment.Version + ")");
