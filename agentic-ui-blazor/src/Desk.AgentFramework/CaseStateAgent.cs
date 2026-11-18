using System.Text.Json;
using AGUI.Abstractions;
using AGUI.Server;
using Desk.Core;
using Microsoft.Agents.AI;
using Microsoft.Extensions.AI;

namespace Desk.AgentFramework;

/// <summary>Marks this assembly for the tests that start the service in memory.</summary>
public sealed class FrameworkService;

/// <summary>
/// State the browser sent comes back to the model as part of the conversation. The endpoint keeps the
/// request it was given on the chat options; this wrapper reads the state from there.
/// </summary>
internal sealed class CaseStateAgent(AIAgent innerAgent) : DelegatingAIAgent(innerAgent)
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
        if (options is ChatClientAgentRunOptions { ChatOptions: { } chatOptions }
            && chatOptions.TryGetRunAgentInput(out RunAgentInput? input)
            && input.State is { ValueKind: JsonValueKind.Object } state)
        {
            messages = [new ChatMessage(ChatRole.System, ScriptedModel.StatePrefix + state.GetRawText()), .. messages];
        }

        return InnerAgent.RunStreamingAsync(messages, session, options, cancellationToken);
    }
}
