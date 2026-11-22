using Microsoft.Extensions.AI;

namespace Desk.Core;

public static class DeskAgent
{
    /// <summary>
    /// The agent is a chat client pipeline: a model, the loop that runs its tool calls, and the tools.
    /// Swap <see cref="ScriptedModel"/> for a real model client and nothing else here changes.
    /// </summary>
    public static IChatClient Create(OrderBook orders, Ledger ledger, TimeSpan wordDelay, Func<Caller> currentCaller)
    {
        IList<AITool> serverTools = new DeskTools(orders, ledger, currentCaller).Create();
        return new ChatClientBuilder(new ScriptedModel(orders, wordDelay))
            .ConfigureOptions(options =>
            {
                options.Tools ??= [];
                foreach (AITool tool in serverTools)
                {
                    options.Tools.Add(tool);
                }
            })
            .UseFunctionInvocation()
            .Build();
    }
}
