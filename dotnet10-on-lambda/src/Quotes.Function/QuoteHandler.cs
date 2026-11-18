using System.Collections.Frozen;
using System.Text.Json;
using System.Text.Json.Serialization;
using Amazon.Lambda.APIGatewayEvents;
using Amazon.Lambda.Core;

namespace Quotes;

public sealed record QuoteRequest(string Sku, int Quantity, string? Country);

public sealed record QuoteResponse(string Sku, int Quantity, decimal UnitPrice, decimal Net, decimal Tax, decimal Total, string Currency);

public sealed record Problem(string Title, string Detail);

/// <summary>
/// The JSON for the request and response bodies, generated at compile time. Native AOT has no reflection-based
/// serializer to fall back on, so every type that crosses the wire is listed here.
/// </summary>
[JsonSourceGenerationOptions(PropertyNamingPolicy = JsonKnownNamingPolicy.CamelCase, PropertyNameCaseInsensitive = true)]
[JsonSerializable(typeof(QuoteRequest))]
[JsonSerializable(typeof(QuoteResponse))]
[JsonSerializable(typeof(Problem))]
public sealed partial class BodyJson : JsonSerializerContext;

/// <summary>The same for the event Lambda delivers and the response it expects back.</summary>
[JsonSerializable(typeof(APIGatewayHttpApiV2ProxyRequest))]
[JsonSerializable(typeof(APIGatewayHttpApiV2ProxyResponse))]
public sealed partial class EventJson : JsonSerializerContext;

/// <summary>A price quote. Created once per execution environment; Handle runs once per request.</summary>
public sealed class QuoteHandler
{
    private const int CatalogueSize = 50_000;
    private static readonly FrozenDictionary<string, decimal> TaxRates =
        new Dictionary<string, decimal> { ["IE"] = 0.23m, ["DE"] = 0.19m, ["FR"] = 0.20m, ["NL"] = 0.21m }.ToFrozenDictionary(StringComparer.OrdinalIgnoreCase);
    private static readonly Dictionary<string, string> JsonHeaders = new() { ["content-type"] = "application/json" };

    private readonly FrozenDictionary<string, decimal> _prices;

    public QuoteHandler()
    {
        // Stands in for the work a real function does once at start-up: reading configuration, building lookup
        // tables, creating clients. It is deterministic so every build of the function holds the same catalogue.
        Dictionary<string, decimal> prices = new(CatalogueSize);
        for (int i = 1; i <= CatalogueSize; i++)
        {
            prices[$"SKU-{i:D5}"] = 1.00m + (i * 7919 % 49_900) / 100m;
        }
        _prices = prices.ToFrozenDictionary(StringComparer.Ordinal);
        InstanceId = Guid.NewGuid().ToString("N");
    }

    /// <summary>Unique to one execution environment. After a SnapStart restore it has to be issued again.</summary>
    public string InstanceId { get; private set; }

    public int Handled { get; private set; }

    public APIGatewayHttpApiV2ProxyResponse Handle(APIGatewayHttpApiV2ProxyRequest request, ILambdaContext context)
    {
        Handled++;
        QuoteRequest? quote;
        try
        {
            quote = string.IsNullOrWhiteSpace(request.Body) ? null : Read(request.Body);
        }
        catch (JsonException)
        {
            return Respond(400, new Problem("Bad request", "The body is not a quote request."));
        }
        if (quote is null || string.IsNullOrWhiteSpace(quote.Sku) || quote.Quantity is < 1 or > 10_000)
        {
            return Respond(400, new Problem("Bad request", "A quote needs a sku and a quantity from 1 to 10000."));
        }
        if (!_prices.TryGetValue(quote.Sku, out decimal unitPrice))
        {
            return Respond(404, new Problem("Not found", $"There is no product {quote.Sku}."));
        }
        decimal net = unitPrice * quote.Quantity;
        decimal tax = decimal.Round(net * TaxRates.GetValueOrDefault(quote.Country ?? "", 0m), 2, MidpointRounding.AwayFromZero);
        return Respond(200, new QuoteResponse(quote.Sku, quote.Quantity, unitPrice, net, tax, net + tax, "EUR"));
    }

    /// <summary>Runs the whole request path once, so that code is compiled and caches are filled before a snapshot is taken.</summary>
    public void Warm() =>
        Handle(new APIGatewayHttpApiV2ProxyRequest { Body = """{"sku":"SKU-00001","quantity":1,"country":"IE"}""" }, null!);

    /// <summary>Everything that must differ between two environments restored from the same snapshot.</summary>
    public void BecomeANewInstance()
    {
        InstanceId = Guid.NewGuid().ToString("N");
        Handled = 0;
    }

#if REFLECTION_JSON
    // The serializer finds the properties of QuoteRequest by reflection at run time. Fine under a JIT; not under Native AOT.
    private static readonly JsonSerializerOptions Reflected = new(JsonSerializerDefaults.Web);
    private static QuoteRequest? Read(string body) => JsonSerializer.Deserialize<QuoteRequest>(body, Reflected);
    private static string Write<T>(T value) => JsonSerializer.Serialize(value, Reflected);
#else
    private static QuoteRequest? Read(string body) => JsonSerializer.Deserialize(body, BodyJson.Default.QuoteRequest);
    private static string Write<T>(T value) => JsonSerializer.Serialize(value, typeof(T), BodyJson.Default);
#endif

    private APIGatewayHttpApiV2ProxyResponse Respond<T>(int status, T body) => new()
    {
        StatusCode = status,
        Headers = new Dictionary<string, string>(JsonHeaders) { ["x-instance"] = InstanceId },
        Body = Write(body),
    };
}
