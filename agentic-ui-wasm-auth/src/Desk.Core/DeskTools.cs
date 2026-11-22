using System.ComponentModel;
using System.Text.Json;
using System.Text.Json.Serialization.Metadata;
using Microsoft.Extensions.AI;

namespace Desk.Core;

/// <summary>The three tools the agent can call. Only the refund changes anything, and it needs a person's approval.</summary>
public sealed class DeskTools(OrderBook orders, Ledger ledger, Func<Caller> currentCaller)
{
    public const string GetOrderName = "get_order";
    public const string RefundOrderName = "refund_order";
    public const string DraftReplyName = "draft_reply";

    private static readonly JsonSerializerOptions s_json = new(JsonSerializerDefaults.Web) { TypeInfoResolver = new DefaultJsonTypeInfoResolver() };

    public IList<AITool> Create() =>
    [
        AIFunctionFactory.Create(GetOrder, GetOrderName, "Look up one order by its id.", s_json),
        // The wrapper is the whole approval mechanism on the server: the function-invoking client
        // asks for approval instead of calling the function, and calls it only when the answer is yes.
        new ApprovalRequiredAIFunction(
            AIFunctionFactory.Create(RefundOrder, RefundOrderName, "Refund an order, in full or in part.", s_json)),
        AIFunctionFactory.Create(DraftReply, DraftReplyName, "Write a draft reply to the customer about an order.", s_json),
    ];

    private Order? GetOrder([Description("The order id, such as O-1001")] string orderId) => orders.Find(orderId);

    private RefundResult RefundOrder(string orderId, decimal amount, string reason)
    {
        if (orders.Find(orderId) is not { } order)
        {
            return new("refused", orderId, amount, "No such order.");
        }

        if (amount <= 0 || amount > order.Total)
        {
            return new("refused", order.Id, amount, $"The amount must be between 0.01 and {order.Total:0.00}.");
        }

        // The last check before money moves, and the only one that cannot be skipped by a request written
        // by hand: who is asking, and how much that person may approve.
        Caller caller = currentCaller();
        if (!caller.IsKnown)
        {
            return new("refused", order.Id, amount, "No signed-in person is attached to this request.");
        }

        if (amount > caller.RefundLimit)
        {
            return new("refused", order.Id, amount, $"{caller.Name} can approve refunds up to {caller.RefundLimit:0.00}. A supervisor has to approve this one.");
        }

        // The key comes from what the refund means, not from the tool call, so a repeated
        // approval, a retried request or a second conversation cannot pay twice.
        (Refund stored, bool created) = ledger.Record(new Refund($"refund:{order.Id}", order.Id, amount, reason, caller.Subject));
        return new(created ? "refunded" : "already refunded", order.Id, stored.Amount, created ? "Refund recorded." : "This order was refunded earlier; nothing was paid again.");
    }

    private CaseState DraftReply(string orderId, string tone, string signature = "")
    {
        Order? order = orders.Find(orderId);
        string body = order is null
            ? $"We could not find order {orderId}."
            : tone == "formal"
                ? $"Dear {order.Customer}, your order {order.Id} ({order.Item}) is recorded as {order.Status} with {order.Carrier}."
                : $"Hi {order.Customer}, good news: order {order.Id} ({order.Item}) is {order.Status} with {order.Carrier}.";
        return new(orderId, tone, string.IsNullOrWhiteSpace(signature) ? body : $"{body} Regards, {signature}", signature);
    }
}
