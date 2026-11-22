using Microsoft.Extensions.AI;

namespace Desk.Core;

public static class DeskAgent
{
    /// <summary>
    /// The agent is a chat client pipeline. From the outside in: the tools added to every request, the
    /// loop that runs tool calls and stops for approvals, the meter, and at the bottom the model.
    /// The model is whatever <see cref="ModelFactory"/> returned. Nothing above it changes.
    /// </summary>
    public static IChatClient Create(IChatClient model, OrderBook orders, Ledger ledger, ModelLog log, string instructions)
    {
        IList<AITool> serverTools = new DeskTools(orders, ledger).Create();
        return new ChatClientBuilder(model)
            .ConfigureOptions(options =>
            {
                options.Tools ??= [];
                foreach (AITool tool in serverTools)
                {
                    options.Tools.Add(tool);
                }
            })
            .UseFunctionInvocation()
            .Use(inner => new ModelMeter(inner, log, instructions))
            .Build();
    }
}
