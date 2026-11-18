using Desk.Core;
using Microsoft.Agents.AI;
using Microsoft.Extensions.AI;

namespace Desk.AgentFramework;

/// <summary>What the model was handed on each call: one line per call, roles and kinds of content.</summary>
public sealed class ModelCalls
{
    private readonly Lock _gate = new();
    private readonly List<string> _calls = [];

    public IReadOnlyList<string> Entries
    {
        get { lock (_gate) { return [.. _calls]; } }
    }

    public void Add(string call)
    {
        lock (_gate) { _calls.Add(call); }
    }

    public void Clear()
    {
        lock (_gate) { _calls.Clear(); }
    }
}

/// <summary>Sits directly in front of the model and notes the messages it is given.</summary>
internal sealed class SeenByModel(IChatClient inner, ModelCalls calls) : DelegatingChatClient(inner)
{
    public override Task<ChatResponse> GetResponseAsync(IEnumerable<ChatMessage> messages, ChatOptions? options = null, CancellationToken cancellationToken = default)
    {
        List<ChatMessage> list = [.. messages];
        calls.Add(Describe(list));
        return base.GetResponseAsync(list, options, cancellationToken);
    }

    public override IAsyncEnumerable<ChatResponseUpdate> GetStreamingResponseAsync(IEnumerable<ChatMessage> messages, ChatOptions? options = null, CancellationToken cancellationToken = default)
    {
        List<ChatMessage> list = [.. messages];
        calls.Add(Describe(list));
        return base.GetStreamingResponseAsync(list, options, cancellationToken);
    }

    private static string Describe(List<ChatMessage> messages)
        => string.Join(" | ", messages.Select(m => $"{m.Role.Value}:{string.Join("+", m.Contents.Select(c => c.GetType().Name.Replace("Content", "")))}"));
}

/// <summary>
/// The AG-UI layer rebuilds an approval request from what the client sent and puts it in front of the
/// client's answer. A stored session already holds the request it made, so the rebuilt one is dropped.
/// </summary>
internal sealed class DropEchoedRequestsAgent(AIAgent innerAgent) : DelegatingAIAgent(innerAgent)
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
        List<ChatMessage> kept = [];
        foreach (ChatMessage message in messages)
        {
            if (!message.Contents.Any(c => c is ToolApprovalRequestContent))
            {
                kept.Add(message);
                continue;
            }

            List<AIContent> rest = [.. message.Contents.Where(c => c is not ToolApprovalRequestContent)];
            if (rest.Count > 0)
            {
                kept.Add(new ChatMessage(message.Role, rest) { MessageId = message.MessageId, AuthorName = message.AuthorName });
            }
        }

        return InnerAgent.RunStreamingAsync(kept, session, options, cancellationToken);
    }
}
