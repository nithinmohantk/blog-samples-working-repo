using Microsoft.AspNetCore.Components.AI;

namespace Desk.Client.Components;

/// <summary>
/// A get_order call as a typed object. The source generator fills OrderId from the call's arguments
/// as they arrive and Order from the result when it arrives, so the card can show both stages.
/// </summary>
[ToolBlock("get_order")]
public partial class OrderToolBlock : FunctionInvocationContentBlock
{
    [ToolParameter(Name = "orderId")]
    public string? OrderId { get; set; }

    [ToolResult]
    public OrderInfo? Order { get; set; }
}
