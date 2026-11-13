using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

namespace Smart.Backend.Server;

/// <summary>One permission a request needs: a resource type (or * for "any") and one of c, r, u, d, s.</summary>
public readonly record struct Need(string Type, char Letter)
{
    public override string ToString() => $"system/{Type}.{Letter}";
}

public sealed record Classification(IReadOnlyList<Need> Needs, string? Refusal)
{
    public static Classification Refuse(string reason) => new([], reason);
}

/// <summary>
/// Works out, from the request alone, every permission it needs. The resource type in the path is the easy part.
/// A search can also pull in other resource types, or reveal facts about them, through its parameters, and each
/// of those needs a permission too.
/// </summary>
public static partial class FhirRequestClassifier
{
    [GeneratedRegex("^[A-Z][A-Za-z]+$")]
    private static partial Regex ResourceType();

    [GeneratedRegex(@"^[^:.]+:([A-Z][A-Za-z]+)\.[^.]+$")]
    private static partial Regex TypedChain();

    public static Classification Classify(string method, string path, IReadOnlyList<KeyValuePair<string, string>> query, JsonObject? body, bool insideBundle = false)
    {
        string[] segments = path.Split('/', StringSplitOptions.RemoveEmptyEntries);
        if (segments.Any(s => s.StartsWith('$'))) { return Classification.Refuse("operations are not exposed through this gateway"); }
        bool hasQuery = query.Count > 0;
        List<Need> needs = [];
        string? refusal = null;

        switch (segments)
        {
            case [] when method == "POST" && !insideBundle:
                return ClassifyBundle(body);
            case [] or ["_history"] when method == "GET":
                needs.Add(new Need("*", 's'));
                refusal = SearchNeeds(query, needs);
                break;
            case [var type] when ResourceType().IsMatch(type):
                switch (method)
                {
                    case "GET": needs.Add(new Need(type, 's')); refusal = SearchNeeds(query, needs); break;
                    case "POST": needs.Add(new Need(type, 'c')); break;
                    // A conditional update or delete is a search and a write in one request, and needs both permissions.
                    case "PUT" or "PATCH" when hasQuery: needs.Add(new Need(type, 'u')); needs.Add(new Need(type, 's')); refusal = SearchNeeds(query, needs); break;
                    case "DELETE" when hasQuery: needs.Add(new Need(type, 'd')); needs.Add(new Need(type, 's')); refusal = SearchNeeds(query, needs); break;
                    default: refusal = $"{method} is not supported on a resource type"; break;
                }
                break;
            case [var type, "_history"] when ResourceType().IsMatch(type) && method == "GET":
                needs.Add(new Need(type, 's'));
                break;
            case [var type, "_search"] when ResourceType().IsMatch(type):
                refusal = "search by POST is not exposed through this gateway; use GET";
                break;
            case [_, _] or [_, _, "_history"] or [_, _, "_history", _] when ResourceType().IsMatch(segments[0]):
                if (segments.Length > 2 && method != "GET") { refusal = "history is read-only"; break; }
                needs.Add(new Need(segments[0], method switch { "GET" => 'r', "PUT" or "PATCH" => 'u', "DELETE" => 'd', _ => '?' }));
                if (needs[^1].Letter == '?') { refusal = $"{method} is not supported on a resource"; }
                break;
            case [var compartment, _, var type] when ResourceType().IsMatch(compartment) && ResourceType().IsMatch(type) && method == "GET":
                needs.Add(new Need(compartment, 'r'));
                needs.Add(new Need(type, 's'));
                refusal = SearchNeeds(query, needs);
                break;
            default:
                refusal = "this request shape is not exposed through this gateway";
                break;
        }
        return new Classification([.. needs.Distinct()], refusal);
    }

    /// <summary>A batch or transaction is judged by what is inside it: every entry needs its own permission.</summary>
    private static Classification ClassifyBundle(JsonObject? bundle)
    {
        if (bundle?["resourceType"]?.GetValue<string>() != "Bundle" || bundle["type"]?.GetValue<string>() is not ("batch" or "transaction") || bundle["entry"] is not JsonArray entries)
        {
            return Classification.Refuse("a POST to the base must be a batch or transaction Bundle");
        }
        List<Need> needs = [];
        foreach (JsonNode? entry in entries)
        {
            if (entry?["request"]?["method"]?.GetValue<string>() is not string method || entry["request"]?["url"]?.GetValue<string>() is not string url)
            {
                return Classification.Refuse("a Bundle entry has no request");
            }
            if (Uri.TryCreate(url, UriKind.Absolute, out _)) { return Classification.Refuse("a Bundle entry addresses an absolute URL"); }
            string[] parts = url.Split('?', 2);
            Classification inner = Classify(method.ToUpperInvariant(), parts[0], ParseQuery(parts.Length > 1 ? parts[1] : ""), null, insideBundle: true);
            if (inner.Refusal is not null) { return Classification.Refuse($"Bundle entry {method} {parts[0]}: {inner.Refusal}"); }
            needs.AddRange(inner.Needs);
            // "Create unless one already exists" searches before it writes.
            if (entry["request"]?["ifNoneExist"] is not null) { needs.Add(new Need(parts[0].Trim('/'), 's')); }
        }
        return new Classification([.. needs.Distinct()], null);
    }

    /// <summary>The permissions a search needs beyond its own resource type. Returns a refusal, or null.</summary>
    private static string? SearchNeeds(IReadOnlyList<KeyValuePair<string, string>> query, List<Need> needs)
    {
        foreach ((string key, string value) in query)
        {
            string name = key.Split(':')[0];
            switch (name)
            {
                case "_include":
                    // Patient?_include=Patient:general-practitioner:Practitioner returns Practitioner resources.
                    if (value == "*") { needs.Add(new Need("*", 'r')); break; }
                    string[] include = value.Split(':');
                    if (include.Length < 3 || !ResourceType().IsMatch(include[2])) { return $"_include must name its target type, as Source:parameter:Type ('{value}')"; }
                    needs.Add(new Need(include[2], 'r'));
                    break;
                case "_revinclude":
                    // Patient?_revinclude=Observation:subject returns every Observation that points at the patients found.
                    if (value == "*") { needs.Add(new Need("*", 'r')); break; }
                    string source = value.Split(':')[0];
                    if (!ResourceType().IsMatch(source)) { return $"_revinclude '{value}' does not name a resource type"; }
                    needs.Add(new Need(source, 'r'));
                    break;
                case "_has":
                    // Patient?_has:Observation:subject:code=X answers a question about Observations.
                    string[] has = key.Split(':');
                    if (has.Length != 4 || !ResourceType().IsMatch(has[1])) { return $"'{key}' is not a single-level _has"; }
                    needs.Add(new Need(has[1], 's'));
                    break;
                case "_type":
                    foreach (string type in value.Split(',')) { if (!ResourceType().IsMatch(type)) { return "_type lists something that is not a resource type"; } needs.Add(new Need(type, 's')); }
                    break;
                case "_filter" or "_query":
                    return $"{name} is not exposed through this gateway";
                default:
                    if (!key.Contains('.')) { break; }
                    // Observation?subject:Patient.name=Smith answers a question about Patients.
                    if (TypedChain().Match(key) is not { Success: true } chain) { return $"a chained parameter must name its type and go one level deep, as subject:Patient.name ('{key}')"; }
                    needs.Add(new Need(chain.Groups[1].Value, 's'));
                    break;
            }
        }
        return null;
    }

    public static List<KeyValuePair<string, string>> ParseQuery(string query) =>
        [.. query.TrimStart('?').Split('&', StringSplitOptions.RemoveEmptyEntries).Select(pair => pair.Split('=', 2))
            .Select(pair => KeyValuePair.Create(Uri.UnescapeDataString(pair[0].Replace('+', ' ')), pair.Length > 1 ? Uri.UnescapeDataString(pair[1].Replace('+', ' ')) : ""))];
}
