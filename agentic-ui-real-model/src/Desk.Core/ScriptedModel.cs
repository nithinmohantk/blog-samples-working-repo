using System.Globalization;
using System.Runtime.CompilerServices;
using System.Text.Json;
using System.Text.RegularExpressions;
using Microsoft.Extensions.AI;

namespace Desk.Core;

/// <summary>
/// A stand-in for a language model that makes the same decision for the same conversation, every time.
/// It reads the conversation it is given and either streams text or asks for one tool.
/// It is not a model: it exists so that everything around the model can be tested.
/// </summary>
public sealed partial class ScriptedModel(OrderBook orders, TimeSpan wordDelay) : IChatClient
{
    public const string StatePrefix = "Case state: ";

    public async IAsyncEnumerable<ChatResponseUpdate> GetStreamingResponseAsync(
        IEnumerable<ChatMessage> messages,
        ChatOptions? options = null,
        [EnumeratorCancellation] CancellationToken cancellationToken = default)
    {
        List<ChatMessage> conversation = [.. messages];
        ChatMessage? last = conversation.LastOrDefault(message => message.Role != ChatRole.System);
        string messageId = Guid.NewGuid().ToString("N");

        if (last?.Role == ChatRole.Tool && last.Contents.OfType<FunctionResultContent>().LastOrDefault() is { } result)
        {
            FunctionCallContent? call = conversation.SelectMany(message => message.Contents).OfType<FunctionCallContent>().LastOrDefault(c => c.CallId == result.CallId);
            await foreach (ChatResponseUpdate update in SayAsync(messageId, Summarise(call, result), wordDelay, cancellationToken))
            {
                yield return update;
            }

            yield break;
        }

        string prompt = last?.Text ?? "";
        string? orderId = OrderId().Match(prompt) is { Success: true } match ? match.Value.ToUpperInvariant() : null;
        FunctionCallContent? wanted = Decide(prompt, orderId, conversation);
        if (wanted is not null)
        {
            yield return new ChatResponseUpdate(ChatRole.Assistant, [wanted]) { MessageId = messageId, FinishReason = ChatFinishReason.ToolCalls };
            yield break;
        }

        bool slow = prompt.Contains("policy", StringComparison.OrdinalIgnoreCase);
        string text = slow
            ? string.Join(' ', Enumerable.Repeat("Refunds are made to the original payment method after a person approves them.", 12))
            : "I can look up an order, draft a reply to the customer, or prepare a refund for your approval. Give me an order id such as O-1001.";
        await foreach (ChatResponseUpdate update in SayAsync(messageId, text, slow ? TimeSpan.FromMilliseconds(150) : wordDelay, cancellationToken))
        {
            yield return update;
        }
    }

    public Task<ChatResponse> GetResponseAsync(IEnumerable<ChatMessage> messages, ChatOptions? options = null, CancellationToken cancellationToken = default)
        => GetStreamingResponseAsync(messages, options, cancellationToken).ToChatResponseAsync(cancellationToken);

    public object? GetService(Type serviceType, object? serviceKey = null) => serviceType.IsInstanceOfType(this) ? this : null;

    public void Dispose()
    {
    }

    private FunctionCallContent? Decide(string prompt, string? orderId, List<ChatMessage> conversation)
    {
        if (orderId is null)
        {
            return null;
        }

        string callId = "call-" + Guid.NewGuid().ToString("N")[..8];
        if (prompt.Contains("refund", StringComparison.OrdinalIgnoreCase))
        {
            decimal? amount = Amount().Match(prompt) is { Success: true } m ? decimal.Parse(m.Groups[1].Value, CultureInfo.InvariantCulture) : null;
            return new(callId, DeskTools.RefundOrderName, new Dictionary<string, object?>
            {
                ["orderId"] = orderId,
                ["amount"] = amount ?? orders.Find(orderId)?.Total ?? 0m,
                ["reason"] = "Requested at the order desk",
            });
        }

        if (prompt.Contains("draft", StringComparison.OrdinalIgnoreCase) || prompt.Contains("reply", StringComparison.OrdinalIgnoreCase))
        {
            return new(callId, DeskTools.DraftReplyName, new Dictionary<string, object?>
            {
                ["orderId"] = orderId,
                ["tone"] = prompt.Contains("formal", StringComparison.OrdinalIgnoreCase) ? "formal" : "friendly",
                ["signature"] = SignatureFrom(conversation),
            });
        }

        return new(callId, DeskTools.GetOrderName, new Dictionary<string, object?> { ["orderId"] = orderId });
    }

    /// <summary>The shared state reaches the model the way it would reach a real one: as text in the conversation.</summary>
    private static string SignatureFrom(List<ChatMessage> conversation)
    {
        string? state = conversation.LastOrDefault(m => m.Role == ChatRole.System && m.Text.StartsWith(StatePrefix, StringComparison.Ordinal))?.Text;
        if (state is null)
        {
            return "";
        }

        using JsonDocument document = JsonDocument.Parse(state[StatePrefix.Length..]);
        return document.RootElement.TryGetProperty("signature", out JsonElement signature) ? signature.GetString() ?? "" : "";
    }

    private static string Summarise(FunctionCallContent? call, FunctionResultContent result)
    {
        string raw = result.Result?.ToString() ?? "";
        return call?.Name switch
        {
            DeskTools.GetOrderName when raw is "" or "null" => "I could not find that order.",
            DeskTools.GetOrderName => "Here is the order.",
            DeskTools.RefundOrderName when raw.Contains("rejected", StringComparison.OrdinalIgnoreCase) => "No refund was made, because it was not approved.",
            DeskTools.RefundOrderName when raw.Contains("already refunded", StringComparison.Ordinal) => "That order was refunded earlier, so nothing was paid again.",
            DeskTools.RefundOrderName when raw.Contains("refused", StringComparison.Ordinal) => "The refund was refused by the payment rules.",
            DeskTools.RefundOrderName => "The refund is recorded.",
            DeskTools.DraftReplyName => "I put a draft reply in the panel. Edit it, or add a signature and ask again.",
            _ => "Done.",
        };
    }

    private static async IAsyncEnumerable<ChatResponseUpdate> SayAsync(string messageId, string text, TimeSpan delay, [EnumeratorCancellation] CancellationToken cancellationToken)
    {
        string[] words = text.Split(' ');
        for (int i = 0; i < words.Length; i++)
        {
            if (delay > TimeSpan.Zero)
            {
                await Task.Delay(delay, cancellationToken);
            }

            cancellationToken.ThrowIfCancellationRequested();
            yield return new ChatResponseUpdate(ChatRole.Assistant, words[i] + (i < words.Length - 1 ? " " : ""))
            {
                MessageId = messageId,
                FinishReason = i == words.Length - 1 ? ChatFinishReason.Stop : null,
            };
        }
    }

    [GeneratedRegex(@"\bO-\d{4}\b", RegexOptions.IgnoreCase)]
    private static partial Regex OrderId();

    [GeneratedRegex(@"\b(\d+(?:\.\d{1,2})?)\s*(?:euro|eur|€)", RegexOptions.IgnoreCase)]
    private static partial Regex Amount();
}
