using System.Net;
using System.Text;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

namespace FhirFacade.SelfTest;

/// <summary>
/// Stands in for EHRbase. It replays rows recorded from a real repository and applies the filters, order and
/// paging the facade asks for. It is not an AQL engine: it reads the parameters, not the paths.
/// </summary>
public sealed partial class StubRepository : HttpMessageHandler
{
    private readonly JsonArray _columns;
    private readonly List<JsonArray> _rows;

    public StubRepository(string recordedFile)
    {
        JsonNode recorded = JsonNode.Parse(File.ReadAllText(recordedFile))!;
        _columns = recorded["columns"]!.AsArray();
        _rows = [.. recorded["rows"]!.AsArray().Select(row => row!.AsArray())];
    }

    /// <summary>Rows added by a test to provoke a mapping failure. They are served for patient "bad-units".</summary>
    public List<JsonArray> ExtraRows { get; } = [];

    public int Requests { get; private set; }

    [GeneratedRegex(@" LIMIT (?<limit>\d+) OFFSET (?<offset>\d+)$")]
    private static partial Regex Paging();

    [GeneratedRegex(@"^/openehr/v1/ehr/(?<ehr>[0-9a-f-]{36})/composition/(?<composition>[0-9a-f-]{36})$")]
    private static partial Regex CompositionPath();

    protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
    {
        Requests++;
        string path = request.RequestUri!.AbsolutePath;
        Match composition = CompositionPath().Match(path);
        if (request.Method == HttpMethod.Head && composition.Success)
        {
            JsonArray? row = _rows.FirstOrDefault(r =>
                (string)r[0]! == composition.Groups["ehr"].Value
                && ((string)r[2]!).StartsWith(composition.Groups["composition"].Value + "::", StringComparison.Ordinal));
            HttpResponseMessage response = new(row is null ? HttpStatusCode.NotFound : HttpStatusCode.OK);
            if (row is not null)
            {
                response.Headers.TryAddWithoutValidation("ETag", $"\"{(string)row[2]!}\"");
            }

            return response;
        }

        if (request.Method != HttpMethod.Post || path != "/openehr/v1/query/aql")
        {
            return new HttpResponseMessage(HttpStatusCode.NotFound);
        }

        JsonNode body = JsonNode.Parse(await request.Content!.ReadAsStringAsync(cancellationToken))!;
        string aql = (string)body["q"]!;
        JsonObject parameters = body["query_parameters"]!.AsObject();
        string? patient = (string?)parameters["patient_id"];
        if (patient == "repository-down")
        {
            return new HttpResponseMessage(HttpStatusCode.InternalServerError)
            {
                Content = new StringContent("{\"error\":\"Internal Server Error\",\"message\":\"SECRET-BACKEND-DETAIL\"}", Encoding.UTF8, "application/json"),
            };
        }

        IEnumerable<JsonArray> rows = _rows.Concat(ExtraRows);
        if (parameters["composition_uid"] is JsonNode uid)
        {
            rows = rows.Where(r => (string)r[0]! == (string)parameters["ehr_id"]! && (string)r[2]! == (string)uid!);
        }
        else
        {
            rows = rows.Where(r => (string?)r[1] == patient && (string)parameters["namespace"]! == "dataa-demo");
            if (parameters["from"] is JsonNode from)
            {
                rows = rows.Where(r => DateTimeOffset.Parse((string)r[3]!) >= DateTimeOffset.Parse((string)from!));
            }

            if (parameters["before"] is JsonNode before)
            {
                rows = rows.Where(r => DateTimeOffset.Parse((string)r[3]!) < DateTimeOffset.Parse((string)before!));
            }

            rows = aql.Contains("/time/value DESC, c/uid/value ASC LIMIT ", StringComparison.Ordinal)
                ? rows.OrderByDescending(r => DateTimeOffset.Parse((string)r[3]!)).ThenBy(r => (string)r[2]!, StringComparer.Ordinal)
                : rows.OrderBy(r => DateTimeOffset.Parse((string)r[3]!)).ThenBy(r => (string)r[2]!, StringComparer.Ordinal);
            Match paging = Paging().Match(aql);
            rows = rows.Skip(int.Parse(paging.Groups["offset"].Value)).Take(int.Parse(paging.Groups["limit"].Value));
        }

        JsonObject result = new()
        {
            ["q"] = aql,
            ["columns"] = _columns.DeepClone(),
            ["rows"] = new JsonArray([.. rows.Select(r => r.DeepClone())]),
        };
        return new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = new StringContent(result.ToJsonString(), Encoding.UTF8, "application/json"),
        };
    }
}
