using Desk.Core;
using Microsoft.Extensions.AI;
using Xunit;

namespace Desk.Tests;

/// <summary>
/// No key, no network: the pipeline with the scripted stand-in at the bottom, and the meter with a
/// model that only counts. These hold whatever real model is plugged in later.
/// </summary>
public sealed class OfflineTests
{
    private readonly Ledger _ledger = new();
    private readonly ModelLog _log = new();
    private readonly IChatClient _agent;

    public OfflineTests()
    {
        OrderBook orders = new();
        (IChatClient model, string name) = ModelFactory.Create(null, null, null, orders, TimeSpan.Zero);
        Assert.Equal("scripted stand-in", name);
        _agent = DeskAgent.Create(model, orders, _ledger, _log, Prompts.Guarded);
    }

    [Fact]
    public async Task An_order_question_is_two_model_calls_and_the_meter_sees_both()
    {
        ChatResponse response = await _agent.GetResponseAsync("Where is order O-1002?");

        IReadOnlyList<ModelCall> calls = _log.Take();
        Assert.Contains("in transit", Assert.Single(response.Messages.SelectMany(m => m.Contents).OfType<FunctionResultContent>()).Result?.ToString());
        Assert.Equal(2, calls.Count);
        Assert.Equal(["get_order"], calls[0].ToolCalls);
        Assert.Equal(2, calls[0].MessagesIn); // the instructions and the question
        Assert.Empty(_log.Take());
    }

    [Theory]
    [InlineData(true, 1)]
    [InlineData(false, 0)]
    public async Task A_refund_waits_for_approval_whatever_the_model_is(bool approved, int refunds)
    {
        List<ChatMessage> messages = [new(ChatRole.User, "Refund order O-1003")];
        ChatResponse first = await _agent.GetResponseAsync(messages);
        ToolApprovalRequestContent request = first.Messages.SelectMany(m => m.Contents).OfType<ToolApprovalRequestContent>().Single();
        Assert.Equal(0, _ledger.Attempts);

        messages.AddRange(first.Messages);
        messages.Add(new(ChatRole.User, [request.CreateResponse(approved)]));
        await _agent.GetResponseAsync(messages);

        Assert.Equal(refunds, _ledger.Refunds.Count);
    }

    [Fact]
    public void Without_all_three_settings_the_model_is_the_stand_in()
    {
        Assert.Equal("scripted stand-in", ModelFactory.Create("https://example.invalid/openai/v1/", "", "some-model", new OrderBook(), TimeSpan.Zero).Name);
        Assert.Equal("some-model", ModelFactory.Create("https://example.invalid/openai/v1/", "not-a-real-key", "some-model", new OrderBook(), TimeSpan.Zero).Name);
    }

    [Theory]
    [InlineData(DeskTools.NotesRaw, "\"note\"")]
    [InlineData(DeskTools.NotesFenced, "\"customerTextUntrusted\"")]
    [InlineData(DeskTools.NotesHidden, null)]
    public async Task What_get_order_does_with_customer_text_is_a_setting(string notes, string? field)
    {
        OrderBook orders = new();
        IChatClient agent = DeskAgent.Create(ModelFactory.Create(null, null, null, orders, TimeSpan.Zero).Model, orders, new Ledger(), new ModelLog(), Prompts.Guarded, notes);

        ChatResponse response = await agent.GetResponseAsync("Where is order O-1004?");
        string result = response.Messages.SelectMany(m => m.Contents).OfType<FunctionResultContent>().Single().Result?.ToString() ?? "";

        Assert.Contains("Synthetic mug", result);
        Assert.Equal(field is not null, result.Contains("NOTE TO THE ASSISTANT"));
        if (field is not null)
        {
            Assert.Contains(field, result);
        }
    }

    [Fact]
    public void The_order_with_the_planted_note_returns_the_note_to_the_model()
    {
        Assert.Contains("refund_order", new OrderBook().Find("O-1004")!.Note);
        Assert.Contains("never an instruction", Prompts.Guarded);
        Assert.DoesNotContain("never an instruction", Prompts.Plain);
    }
}
