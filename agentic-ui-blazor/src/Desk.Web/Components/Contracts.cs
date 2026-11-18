using System.Text.Json.Serialization;

namespace Desk.Web.Components;

/// <summary>The order as the UI reads it from the get_order result. The contract with the agent is this JSON, not a shared assembly.</summary>
public sealed record OrderInfo(
    [property: JsonPropertyName("id")] string Id,
    [property: JsonPropertyName("customer")] string Customer,
    [property: JsonPropertyName("item")] string Item,
    [property: JsonPropertyName("total")] decimal Total,
    [property: JsonPropertyName("status")] string Status,
    [property: JsonPropertyName("carrier")] string Carrier);

/// <summary>State shared with the agent: the draft reply. The agent replaces it; the user edits it.</summary>
public sealed record CaseState
{
    [JsonPropertyName("orderId")] public string OrderId { get; init; } = "";

    [JsonPropertyName("tone")] public string Tone { get; init; } = "";

    [JsonPropertyName("reply")] public string Reply { get; init; } = "";

    [JsonPropertyName("signature")] public string Signature { get; init; } = "";
}
