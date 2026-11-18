using System.Text.Json;
using FhirMigrationValidator;

// Usage:
//   FhirMigrationValidator --source <url> --target <url> --types Patient,Observation
//                          [--sample 50] [--compare-versions] [--report report.json]
// Tokens are read from the environment variables SOURCE_TOKEN and TARGET_TOKEN, so they never appear in a
// command line or a shell history. Exit code: 0 passed, 1 differences found, 2 the comparison could not run.

Dictionary<string, string> named = [];
HashSet<string> flags = [];
for (int i = 0; i < args.Length; i++)
{
    if (args[i] is "--compare-versions")
    {
        flags.Add(args[i]);
    }
    else if (args[i].StartsWith("--", StringComparison.Ordinal) && i + 1 < args.Length)
    {
        named[args[i]] = args[++i];
    }
}

if (!named.TryGetValue("--source", out string? sourceUrl) || !named.TryGetValue("--target", out string? targetUrl)
    || !named.TryGetValue("--types", out string? types)
    || !Uri.TryCreate(sourceUrl, UriKind.Absolute, out Uri? sourceUri) || !Uri.TryCreate(targetUrl, UriKind.Absolute, out Uri? targetUri))
{
    Console.Error.WriteLine("Required: --source <url> --target <url> --types <Type1,Type2,...>");
    return 2;
}

int sample = named.TryGetValue("--sample", out string? sampleText) && int.TryParse(sampleText, out int parsed) && parsed is > 0 and <= 1000
    ? parsed
    : 50;

using CancellationTokenSource cancellation = new();
Console.CancelKeyPress += (_, e) => { e.Cancel = true; cancellation.Cancel(); };

try
{
    MigrationValidator validator = new(
        FhirServer.Create("source", sourceUri, Environment.GetEnvironmentVariable("SOURCE_TOKEN")),
        FhirServer.Create("target", targetUri, Environment.GetEnvironmentVariable("TARGET_TOKEN")));

    ValidationReport report = await validator.RunAsync(
        new ValidationOptions(types.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries), sample, flags.Contains("--compare-versions")),
        cancellation.Token);

    foreach (TypeResult type in report.Types)
    {
        Console.WriteLine($"{(type.Passed ? "PASS" : "FAIL")}  {type.ResourceType,-22} source {type.SourceCount,8}  target {type.TargetCount,8}  " +
                          $"sampled {type.Sampled,4}  missing {type.MissingOnTarget.Count,3}  different {type.Different.Count,3}");
    }

    Console.WriteLine($"FHIR version: source {report.SourceFhirVersion}, target {report.TargetFhirVersion}");
    Console.WriteLine(report.Passed ? "RESULT: PASSED" : "RESULT: FAILED");

    if (named.TryGetValue("--report", out string? reportPath))
    {
        await File.WriteAllTextAsync(reportPath,
            report.ToJson().ToJsonString(new JsonSerializerOptions { WriteIndented = true }), cancellation.Token);
    }

    return report.Passed ? 0 : 1;
}
catch (Exception ex) when (ex is FhirServerException or HttpRequestException or TaskCanceledException or JsonException)
{
    // The message names the server and the request, never a response body.
    Console.Error.WriteLine($"Could not complete the comparison: {ex.Message}");
    return 2;
}
