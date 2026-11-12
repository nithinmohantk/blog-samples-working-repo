// clinical-coding request <sample root>                 print the schema and instructions that would be sent; no network
// clinical-coding propose <sample root> <note.txt>      call the deployment and print proposals for review
//   needs AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_DEPLOYMENT, and an identity DefaultAzureCredential can find
using System.Text.Json;
using System.Text.Json.Nodes;
using ClinicalCoding.AzureOpenAI;
using ClinicalCoding.Core;

if (args.Length < 2 || args[0] is not ("request" or "propose") || (args[0] == "propose" && args.Length < 3))
{
    Console.Error.WriteLine("Usage: clinical-coding request <sample root> | propose <sample root> <note.txt>");
    return 2;
}

JsonSerializerOptions indented = new() { WriteIndented = true };
CodingSubset subset = CodingSubset.Load(Path.Combine(args[1], "terminology", "coding-subset.json"));
JsonObject schema = ExtractionSchema.Build(subset);
IReadOnlyList<string> problems = ExtractionSchema.Lint(schema);
if (problems.Count > 0)
{
    Console.Error.WriteLine("The schema does not meet the structured output limits:\n  " + string.Join("\n  ", problems));
    return 2;
}

if (args[0] == "request")
{
    Console.WriteLine(new JsonObject
    {
        ["name"] = AzureOpenAIExtractor.SchemaName,
        ["strict"] = true,
        ["schema"] = schema,
        ["system"] = ExtractionSchema.SystemPrompt(subset),
    }.ToJsonString(indented));
    return 0;
}

string? endpoint = Environment.GetEnvironmentVariable("AZURE_OPENAI_ENDPOINT");
string? deployment = Environment.GetEnvironmentVariable("AZURE_OPENAI_DEPLOYMENT");
if (string.IsNullOrWhiteSpace(endpoint) || string.IsNullOrWhiteSpace(deployment))
{
    Console.Error.WriteLine("Set AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_DEPLOYMENT.");
    return 2;
}

using CancellationTokenSource timeout = new(TimeSpan.FromSeconds(90));
try
{
    AzureOpenAIExtractor extractor = new(new Uri(endpoint), deployment, subset);
    IReadOnlyList<Proposal> proposals = await extractor.ProposeAsync(await File.ReadAllTextAsync(args[2], timeout.Token), timeout.Token);
    Console.WriteLine(JsonSerializer.Serialize(proposals, new JsonSerializerOptions { WriteIndented = true, PropertyNamingPolicy = JsonNamingPolicy.CamelCase }));
    return 0;
}
catch (ShapeException ex)
{
    Console.Error.WriteLine($"The response was not used: {ex.Message}");
    return 1;
}
catch (Exception ex) when (ex is InvalidOperationException or OperationCanceledException)
{
    Console.Error.WriteLine($"No proposals: {ex.Message}");
    return 1;
}
