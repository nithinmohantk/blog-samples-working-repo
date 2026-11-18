using Microsoft.Extensions.AI;

namespace TwoClouds.Chat;

/// <summary>
/// Sends requests to the primary provider and retries once on the secondary when the
/// failure is transient. Streaming calls pass through to the primary unchanged.
/// </summary>
public sealed class FailoverChatClient(
    IChatClient primary,
    IChatClient secondary,
    Func<Exception, bool> isTransient,
    ILogger<FailoverChatClient> logger) : DelegatingChatClient(primary)
{
    public override async Task<ChatResponse> GetResponseAsync(
        IEnumerable<ChatMessage> messages,
        ChatOptions? options = null,
        CancellationToken cancellationToken = default)
    {
        // The sequence may be read twice, so materialise it once.
        IReadOnlyList<ChatMessage> history = messages as IReadOnlyList<ChatMessage> ?? messages.ToList();

        try
        {
            return await base.GetResponseAsync(history, options, cancellationToken).ConfigureAwait(false);
        }
        catch (Exception exception) when (isTransient(exception) && !cancellationToken.IsCancellationRequested)
        {
            logger.LogWarning(exception, "Primary chat provider failed with a transient error. Using the secondary provider.");
            return await secondary.GetResponseAsync(history, ForSecondary(options), cancellationToken)
                .ConfigureAwait(false);
        }
    }

    // A model ID chosen for the primary provider means nothing to the secondary one.
    private static ChatOptions? ForSecondary(ChatOptions? options)
    {
        if (options?.ModelId is null)
        {
            return options;
        }

        ChatOptions copy = options.Clone();
        copy.ModelId = null;
        return copy;
    }
}
