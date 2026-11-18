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
