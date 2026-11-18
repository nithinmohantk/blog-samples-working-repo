using Microsoft.Agents.AI;
using Microsoft.Extensions.AI;

namespace Desk.AgentFramework;

/// <summary>
/// An AG-UI client sends the whole conversation with every request, and the AG-UI layer adds a rebuilt
/// approval request in front of the client's answer. A stored session already holds both, so from the
/// client this takes only what follows the last assistant message: the new turn, or the answer.
/// </summary>
internal sealed class NewMessagesOnlyAgent(AIAgent innerAgent) : DelegatingAIAgent(innerAgent)
{
    protected override Task<AgentResponse> RunCoreAsync(
        IEnumerable<ChatMessage> messages,
        AgentSession? session = null,
        AgentRunOptions? options = null,
        CancellationToken cancellationToken = default) =>
        RunCoreStreamingAsync(messages, session, options, cancellationToken).ToAgentResponseAsync(cancellationToken);

    protected override IAsyncEnumerable<AgentResponseUpdate> RunCoreStreamingAsync(
        IEnumerable<ChatMessage> messages,
        AgentSession? session = null,
        AgentRunOptions? options = null,
        CancellationToken cancellationToken = default)
    {
        List<ChatMessage> all = [.. messages];
        int lastFromAssistant = all.FindLastIndex(message => message.Role == ChatRole.Assistant);
        return InnerAgent.RunStreamingAsync(all[(lastFromAssistant + 1)..], session, options, cancellationToken);
    }
}
