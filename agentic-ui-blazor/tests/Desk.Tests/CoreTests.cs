using Desk.Core;
using Microsoft.Extensions.AI;
using Xunit;

namespace Desk.Tests;

/// <summary>Layer 1: the agent as a chat client, with nothing around it. No HTTP, no UI.</summary>
public sealed class CoreTests
{
    private readonly Ledger _ledger = new();
    private readonly IChatClient _agent;

    public CoreTests() => _agent = DeskAgent.Create(new OrderBook(), _ledger, TimeSpan.Zero);

    [Fact]
    public async Task A_question_without_an_order_is_answered_in_text()
    {
        ChatResponse response = await _agent.GetResponseAsync("hello");
        Assert.Contains("order id", response.Text);
        Assert.Empty(_ledger.Refunds);
    }

    [Fact]
    public async Task An_order_question_calls_get_order_and_returns_its_result()
    {
        ChatResponse response = await _agent.GetResponseAsync("Where is order O-1002?");
        FunctionResultContent result = Assert.Single(response.Messages.SelectMany(m => m.Contents).OfType<FunctionResultContent>());
        Assert.Contains("in transit", result.Result?.ToString());
    }

    [Fact]
    public async Task A_refund_stops_for_approval_and_pays_nothing()
    {
        ChatResponse response = await _agent.GetResponseAsync("Refund order O-1003");
        Assert.Single(response.Messages.SelectMany(m => m.Contents).OfType<ToolApprovalRequestContent>());
        Assert.Equal(0, _ledger.Attempts);
    }

    [Theory]
    [InlineData(true, 1, "recorded")]
    [InlineData(false, 0, "No refund was made")]
    public async Task The_answer_to_the_approval_decides_whether_money_moves(bool approved, int refunds, string says)
    {
        List<ChatMessage> messages = [new(ChatRole.User, "Refund order O-1003")];
        ChatResponse first = await _agent.GetResponseAsync(messages);
        ToolApprovalRequestContent request = first.Messages.SelectMany(m => m.Contents).OfType<ToolApprovalRequestContent>().Single();
        messages.AddRange(first.Messages);
        messages.Add(new(ChatRole.User, [request.CreateResponse(approved)]));

        ChatResponse second = await _agent.GetResponseAsync(messages);

        Assert.Equal(refunds, _ledger.Refunds.Count);
        Assert.Contains(says, second.Text);
    }

    [Fact]
    public void The_ledger_records_one_refund_per_key()
    {
        Refund refund = new("refund:O-1003", "O-1003", 37.50m, "test");
        Assert.True(_ledger.Record(refund).Created);
        Assert.False(_ledger.Record(refund with { Amount = 10m }).Created);
        Assert.Equal(37.50m, Assert.Single(_ledger.Refunds).Amount);
        Assert.Equal(2, _ledger.Attempts);
    }

    [Fact]
    public async Task A_refund_above_the_order_total_is_refused_even_when_approved()
    {
        List<ChatMessage> messages = [new(ChatRole.User, "Refund 900 euro on order O-1002")];
        ChatResponse first = await _agent.GetResponseAsync(messages);
        ToolApprovalRequestContent request = first.Messages.SelectMany(m => m.Contents).OfType<ToolApprovalRequestContent>().Single();
        messages.AddRange(first.Messages);
        messages.Add(new(ChatRole.User, [request.CreateResponse(true)]));

        ChatResponse second = await _agent.GetResponseAsync(messages);

        Assert.Empty(_ledger.Refunds);
        Assert.Contains("refused", second.Text);
    }
}
