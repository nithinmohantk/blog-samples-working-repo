using System.Diagnostics;
using System.Diagnostics.Metrics;
using System.Runtime.CompilerServices;
using Microsoft.Extensions.AI;

namespace TwoClouds.Chat;

/// <summary>
/// Records the tokens each provider actually bills. It sits below the cache, so a cache hit records nothing.
/// </summary>
public sealed class UsageMeteringChatClient : DelegatingChatClient
{
    public const string MeterName = "TwoClouds.Chat.Usage";

    private readonly Counter<long> _inputTokens;
    private readonly Counter<long> _outputTokens;
    private readonly string _provider;

    public UsageMeteringChatClient(IChatClient innerClient, IMeterFactory meterFactory, string provider)
        : base(innerClient)
    {
        Meter meter = meterFactory.Create(MeterName);
        _inputTokens = meter.CreateCounter<long>("chat.tokens.input", unit: "{token}");
        _outputTokens = meter.CreateCounter<long>("chat.tokens.output", unit: "{token}");
        _provider = provider;
    }

    public override async Task<ChatResponse> GetResponseAsync(
        IEnumerable<ChatMessage> messages,
        ChatOptions? options = null,
        CancellationToken cancellationToken = default)
    {
        ChatResponse response = await base.GetResponseAsync(messages, options, cancellationToken)
            .ConfigureAwait(false);
        Record(response.Usage, response.ModelId ?? options?.ModelId);
        return response;
    }

    public override async IAsyncEnumerable<ChatResponseUpdate> GetStreamingResponseAsync(
        IEnumerable<ChatMessage> messages,
        ChatOptions? options = null,
        [EnumeratorCancellation] CancellationToken cancellationToken = default)
    {
        await foreach (ChatResponseUpdate update in base.GetStreamingResponseAsync(messages, options, cancellationToken)
            .ConfigureAwait(false))
        {
            // Providers report streaming usage as a content item, usually on the final update.
            foreach (UsageContent usage in update.Contents.OfType<UsageContent>())
            {
                Record(usage.Details, update.ModelId ?? options?.ModelId);
            }

            yield return update;
        }
    }

    private void Record(UsageDetails? usage, string? modelId)
    {
        if (usage is null)
        {
            return;
        }

        // Keep tags low-cardinality: provider and model, never a user or tenant identifier.
        TagList tags = new() { { "provider", _provider }, { "model", modelId ?? "unknown" } };

        if (usage.InputTokenCount is long input)
        {
            _inputTokens.Add(input, tags);
        }

        if (usage.OutputTokenCount is long output)
        {
            _outputTokens.Add(output, tags);
        }
    }
}
