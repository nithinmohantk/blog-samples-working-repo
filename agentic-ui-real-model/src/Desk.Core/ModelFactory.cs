using System.ClientModel;
using Microsoft.Extensions.AI;
using OpenAI;
using OpenAI.Chat;

namespace Desk.Core;

/// <summary>
/// The one place that knows which model is behind the agent. With an endpoint, a key and a model name
/// it is a real model on any endpoint that speaks the OpenAI chat API, Azure OpenAI's /openai/v1/ included.
/// Without them it is the scripted stand-in, so everything still runs with no account.
/// </summary>
public static class ModelFactory
{
    public static (IChatClient Model, string Name) Create(string? endpoint, string? key, string? model, OrderBook orders, TimeSpan wordDelay)
    {
        if (string.IsNullOrWhiteSpace(endpoint) || string.IsNullOrWhiteSpace(key) || string.IsNullOrWhiteSpace(model))
        {
            return (new ScriptedModel(orders, wordDelay), "scripted stand-in");
        }

        ChatClient client = new(model, new ApiKeyCredential(key), new OpenAIClientOptions { Endpoint = new Uri(endpoint) });
        return (client.AsIChatClient(), model);
    }
}
