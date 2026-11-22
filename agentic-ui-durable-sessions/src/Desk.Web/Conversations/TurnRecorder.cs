using System.Runtime.CompilerServices;
using Microsoft.Extensions.AI;

namespace Desk.Web.Conversations;

/// <summary>
/// Sits between the UI agent and the chat client and writes down a turn while it is happening:
/// the message that started it, then every update as it comes off the wire.
/// </summary>
public sealed class TurnRecorder(IChatClient inner, JournalThread thread) : DelegatingChatClient(inner)
{
    public override async IAsyncEnumerable<ChatResponseUpdate> GetStreamingResponseAsync(
        IEnumerable<ChatMessage> messages,
        ChatOptions? options = null,
        [EnumeratorCancellation] CancellationToken cancellationToken = default)
    {
        List<ChatMessage> conversation = [.. messages];
        if (conversation.LastOrDefault(message => message.Role == ChatRole.User) is { } asked)
        {
            thread.LiveStart(asked);
        }

        bool anything = false;
        await using IAsyncEnumerator<ChatResponseUpdate> updates = base.GetStreamingResponseAsync(conversation, options, cancellationToken).GetAsyncEnumerator(cancellationToken);
        while (true)
        {
            ChatResponseUpdate update;
            try
            {
                if (!await updates.MoveNextAsync())
                {
                    break;
                }

                update = updates.Current;
            }
            catch (Exception) when (!anything)
            {
                // Refused before the first event, for example an approval somebody else already answered.
                thread.LiveAbandon();
                throw;
            }

            anything = true;
            thread.Live(update);
            yield return update;
        }
    }
}
