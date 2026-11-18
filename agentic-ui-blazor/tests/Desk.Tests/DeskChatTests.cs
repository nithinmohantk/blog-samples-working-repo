using AngleSharp.Dom;
using Bunit;
using Desk.Core;
using Desk.Web.Components;
using Microsoft.Extensions.AI;
using Microsoft.Extensions.DependencyInjection;
using Xunit;

namespace Desk.Tests;

/// <summary>
/// Layer 3: the Blazor component, rendered in memory by bUnit with the agent pipeline plugged in
/// directly. No browser, no HTTP. A test types, clicks and reads the markup.
/// </summary>
public sealed class DeskChatTests : BunitContext
{
    private static readonly TimeSpan s_wait = TimeSpan.FromSeconds(10);
    private readonly Ledger _ledger = new();

    public DeskChatTests()
    {
        JSInterop.Mode = JSRuntimeMode.Loose;
        Services.AddLogging();
        Services.AddSingleton<IChatClient>(DeskAgent.Create(new OrderBook(), _ledger, TimeSpan.Zero));
    }

    [Fact]
    public void An_answer_in_text_appears_in_the_message_list()
    {
        IRenderedComponent<DeskChat> chat = Ask("hello");
        chat.WaitForAssertion(() => Assert.Contains("Give me an order id", chat.Markup), s_wait);
    }

    [Fact]
    public void An_order_lookup_is_drawn_as_a_card_with_typed_data()
    {
        IRenderedComponent<DeskChat> chat = Ask("Where is order O-1001?");

        IElement card = chat.WaitForElement(".order-card[data-order='O-1001']", s_wait);
        Assert.Contains("Synthetic kettle", card.TextContent);
        Assert.Equal("delivered", card.QuerySelector(".order-card__status")!.TextContent);
        chat.WaitForAssertion(() => Assert.Contains("Here is the order.", chat.Markup), s_wait);
    }

    [Fact]
    public void A_refund_waits_for_a_click_and_pays_after_Approve()
    {
        IRenderedComponent<DeskChat> chat = Ask("Refund order O-1003");

        chat.WaitForElement(".sc-ai-approval", s_wait);
        Assert.Contains("refund_order", chat.Find(".sc-ai-approval__tool-name").TextContent);
        Assert.Equal(0, _ledger.Attempts);

        Button(chat, "Approve").Click();

        chat.WaitForAssertion(() => Assert.Single(_ledger.Refunds), s_wait);
        chat.WaitForAssertion(() => Assert.Contains("The refund is recorded.", chat.Markup), s_wait);
        Assert.Empty(chat.FindAll(".sc-ai-approval__actions"));
    }

    [Fact]
    public void A_rejected_refund_pays_nothing_and_says_so()
    {
        IRenderedComponent<DeskChat> chat = Ask("Refund order O-1003");
        chat.WaitForElement(".sc-ai-approval", s_wait);

        Button(chat, "Reject").Click();

        chat.WaitForAssertion(() => Assert.Contains("No refund was made", chat.Markup), s_wait);
        Assert.Equal(0, _ledger.Attempts);
        Assert.Contains("Rejected", chat.Find(".sc-ai-approval__status").TextContent);
    }

    [Fact]
    public void The_input_is_disabled_while_an_approval_is_pending()
    {
        IRenderedComponent<DeskChat> chat = Ask("Refund order O-1003");
        chat.WaitForElement(".sc-ai-approval", s_wait);
        Assert.True(chat.Find("textarea.sc-ai-input__textarea").HasAttribute("disabled"));
    }

    private IRenderedComponent<DeskChat> Ask(string text)
    {
        IRenderedComponent<DeskChat> chat = Render<DeskChat>();
        chat.Find("textarea.sc-ai-input__textarea").Input(text);
        chat.Find("button.sc-ai-input__send").Click();
        return chat;
    }

    private static IElement Button(IRenderedComponent<DeskChat> chat, string label)
        => chat.FindAll(".sc-ai-approval button").Single(button => button.TextContent.Trim() == label);
}
