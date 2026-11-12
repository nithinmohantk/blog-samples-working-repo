using System.Text.Json;
using Firely.Fhir.Packages;
using Firely.Fhir.Validation;
using Hl7.Fhir.Model;
using Hl7.Fhir.Serialization;
using Hl7.Fhir.Specification;
using Hl7.Fhir.Specification.Source;
using Hl7.Fhir.Specification.Terminology;

// Usage: FhirGate --package hl7.fhir.uv.ips@2.0.0 --out firely.json <file.json> [<file.json> ...]
// Validates each resource against the profile it declares in meta.profile, with the Firely .NET SDK, and
// writes {file: [{severity, code, message, location}]} in the shape fhir_gate.py reads.
// Exit code: 0 when the run completed (whatever it found), 2 when it could not run.

List<string> packages = [], files = [];
string output = "firely.json";
for (int i = 0; i < args.Length; i++)
{
    switch (args[i])
    {
        case "--package": packages.Add(args[++i]); break;
        case "--out": output = args[++i]; break;
        default: files.Add(args[i]); break;
    }
}

if (files.Count == 0)
{
    Console.Error.WriteLine("No files given.");
    return 2;
}

const string PackageServer = "https://packages.simplifier.net";
try
{
    // Core definitions plus the implementation guides, resolved from the package server and cached on disk.
    FhirPackageSource core = FhirPackageSource.CreateCorePackageSource(ModelInfo.ModelInspector, FhirRelease.R4, PackageServer);
    FhirPackageSource guides = new(ModelInfo.ModelInspector, PackageServer, [.. packages]);
    CachedResolver resolver = new(new MultiResolver(guides, core));

    // Value sets that can be expanded from the packages are checked locally. Codes from large external code
    // systems such as SNOMED CT are not: that takes a terminology server.
    LocalTerminologyService terminology = new(resolver);
    Validator validator = new(resolver, terminology);
    FhirJsonParser parser = new();

    Dictionary<string, List<Finding>> results = [];
    foreach (string file in files)
    {
        List<Finding> findings = [];
        results[Path.GetFileName(file)] = findings;
        Resource resource;
        try
        {
            resource = parser.Parse<Resource>(await File.ReadAllTextAsync(file));
        }
        catch (Exception ex) when (ex is FormatException or DeserializationFailedException or InvalidOperationException)
        {
            // Content that is not valid FHIR at all never reaches profile validation.
            findings.Add(new Finding("error", "structure", ex.Message, ""));
            continue;
        }

        string? profile = resource.Meta?.Profile?.FirstOrDefault();
        OperationOutcome outcome = profile is null ? validator.Validate(resource) : validator.Validate(resource, profile);
        findings.AddRange(outcome.Issue.Select(issue => new Finding(
            issue.Severity?.ToString().ToLowerInvariant() ?? "error",
            issue.Code?.ToString() ?? "",
            issue.Details?.Text ?? issue.Diagnostics ?? "",
            string.Join("; ", issue.Expression ?? []))));
    }

    await File.WriteAllTextAsync(output, JsonSerializer.Serialize(results, new JsonSerializerOptions { WriteIndented = true, PropertyNamingPolicy = JsonNamingPolicy.CamelCase }));
    foreach ((string file, List<Finding> findings) in results)
    {
        int errors = findings.Count(f => f.Severity is "error" or "fatal");
        Console.WriteLine($"{(errors == 0 ? "ok  " : "FAIL")}  {file}  ({errors} error(s), {findings.Count - errors} other)");
    }

    return 0;
}
catch (Exception ex)
{
    Console.Error.WriteLine($"The validation run could not complete: {ex.GetType().Name}: {ex.Message}");
    return 2;
}

internal sealed record Finding(string Severity, string Code, string Message, string Location);
