using System.Text.Json.Serialization;

namespace Desk.Core;

/// <summary>An order as the tools return it. Every order here is invented.</summary>
public sealed record Order(
    [property: JsonPropertyName("id")] string Id,
    [property: JsonPropertyName("customer")] string Customer,
    [property: JsonPropertyName("item")] string Item,
    [property: JsonPropertyName("total")] decimal Total,
    [property: JsonPropertyName("status")] string Status,
    [property: JsonPropertyName("carrier")] string Carrier);

/// <summary>The outcome of a refund request.</summary>
public sealed record RefundResult(
    [property: JsonPropertyName("status")] string Status,
    [property: JsonPropertyName("orderId")] string OrderId,
    [property: JsonPropertyName("amount")] decimal Amount,
    [property: JsonPropertyName("detail")] string Detail);

/// <summary>The state the agent and the user both edit: a draft reply to the customer.</summary>
public sealed record CaseState(
    [property: JsonPropertyName("orderId")] string OrderId,
    [property: JsonPropertyName("tone")] string Tone,
    [property: JsonPropertyName("reply")] string Reply,
    [property: JsonPropertyName("signature")] string Signature);

public sealed class OrderBook
{
    private readonly Dictionary<string, Order> _orders = new(StringComparer.OrdinalIgnoreCase)
    {
        ["O-1001"] = new("O-1001", "Test Customer One", "Synthetic kettle", 42.00m, "delivered", "Example Post"),
        ["O-1002"] = new("O-1002", "Test Customer Two", "Synthetic desk lamp", 18.25m, "in transit", "Example Courier"),
        ["O-1003"] = new("O-1003", "Test Customer Three", "Synthetic headphones", 37.50m, "delivered", "Example Post"),
    };

    public Order? Find(string orderId) => _orders.GetValueOrDefault(orderId);
}
