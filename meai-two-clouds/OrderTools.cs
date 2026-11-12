using System.ComponentModel;

namespace TwoClouds.Chat;

public sealed class OrderTools
{
    [Description("Returns the current fulfilment status of an order.")]
    public string GetOrderStatus(
        [Description("The order identifier, for example ORD-10042.")] string orderId) =>
        // Replace with a real lookup. Validate and authorise here: the model chooses the arguments.
        orderId.StartsWith("ORD-", StringComparison.Ordinal) ? "SHIPPED" : "UNKNOWN";
}
