using System.Diagnostics;
using System.Runtime.CompilerServices;
using Microsoft.Extensions.AI;

namespace Desk.Core;

/// <summary>One call to the model, as measured from the agent's side.</summary>
public sealed record ModelCall(int MessagesIn, long? InputTokens, long? OutputTokens, double FirstUpdateMs, double TotalMs, IReadOnlyList<string> ToolCalls, string? Finish);

public sealed class ModelLog
{
    private readonly Lock _gate = new();
    private readonly List<ModelCall> _calls = [];

    public void Add(ModelCall call)
    {
        lock (_gate) { _calls.Add(call); }
    }

    /// <summary>Returns the calls made since the last time this was asked, and forgets them.</summary>
    public IReadOnlyList<ModelCall> Take()
    {
        lock (_gate)
        {
            ModelCall[] taken = [.. _calls];
            _calls.Clear();
            return taken;
        }
    }
}

/// <summary>
/// Sits directly on the model, under the tool loop, and adds the instructions to every call.
/// It records what each call cost: messages sent, tokens, time to the first update, total time.
/// </summary>
public sealed class ModelMeter(IChatClient inner, ModelLog log, string instructions) : DelegatingChatClient(inner)
{
    public override async IAsyncEnumerable<ChatResponseUpdate> GetStreamingResponseAsync(
        IEnumerable<ChatMessage> messages,
        ChatOptions? options = null,
        [EnumeratorCancellation] CancellationToken cancellationToken = default)
    {
        List<ChatMessage> conversation = [new(ChatRole.System, instructions), .. messages];
        Stopwatch watch = Stopwatch.StartNew();
        double? first = null;
        long? input = null, output = null;
        List<string> tools = [];
        string? finish = null;
        try
        {
            await foreach (ChatResponseUpdate update in base.GetStreamingResponseAsync(conversation, options, cancellationToken))
            {
                first ??= watch.Elapsed.TotalMilliseconds;
                foreach (AIContent content in update.Contents)
                {
                    switch (content)
                    {
                        case UsageContent usage:
                            input = usage.Details.InputTokenCount ?? input;
                            output = usage.Details.OutputTokenCount ?? output;
                            break;
                        case FunctionCallContent call:
                            tools.Add(call.Name);
                            break;
                    }
                }

                finish = update.FinishReason?.Value ?? finish;
                yield return update;
            }
        }
        finally
        {
            log.Add(new ModelCall(conversation.Count, input, output, first ?? watch.Elapsed.TotalMilliseconds, watch.Elapsed.TotalMilliseconds, tools, finish));
        }
    }

    public override Task<ChatResponse> GetResponseAsync(IEnumerable<ChatMessage> messages, ChatOptions? options = null, CancellationToken cancellationToken = default)
        => GetStreamingResponseAsync(messages, options, cancellationToken).ToChatResponseAsync(cancellationToken);
}
