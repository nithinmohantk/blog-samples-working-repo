// OrderAgentClient.cs
// NOT COMPILED by the author. Written against the public source of the A2A and
// Microsoft.Agents.AI.A2A packages (preview in July 2026). Build and adjust to your pinned versions.
//
//   dotnet add package Microsoft.Agents.AI.A2A --prerelease
//   dotnet add package Azure.Identity
using System.Net.Http.Headers;
using A2A;
using Azure.Core;
using Microsoft.Agents.AI;

/// <summary>Adds what AgentCore Runtime expects on every call: a bearer token and a session id.</summary>
public sealed class AgentCoreAuthHandler(TokenCredential credential, string scope, string sessionId)
    : DelegatingHandler
{
    protected override async Task<HttpResponseMessage> SendAsync(
        HttpRequestMessage request, CancellationToken cancellationToken)
    {
        // Azure.Identity caches and refreshes the token; asking per request is cheap.
        AccessToken token = await credential.GetTokenAsync(new TokenRequestContext([scope]), cancellationToken);
        request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", token.Token);
        request.Headers.TryAddWithoutValidation("X-Amzn-Bedrock-AgentCore-Runtime-Session-Id", sessionId);
        return await base.SendAsync(request, cancellationToken);
    }
}

public static class OrderAgentClient
{
    /// <param name="runtimeUrl">The AgentCore invocation URL, ending in /invocations/.</param>
    /// <param name="scope">The scope of the app registration the runtime's JWT authorizer trusts.</param>
    public static async Task<AIAgent> ConnectAsync(
        Uri runtimeUrl, TokenCredential credential, string scope, CancellationToken cancellationToken)
    {
        // AgentCore rejects session ids shorter than 33 characters. A hyphenated GUID is 36.
        string sessionId = Guid.NewGuid().ToString("D");

        var http = new HttpClient(new AgentCoreAuthHandler(credential, scope, sessionId)
        {
            InnerHandler = new SocketsHttpHandler { PooledConnectionLifetime = TimeSpan.FromMinutes(5) }
        })
        {
            Timeout = TimeSpan.FromSeconds(100)
        };

        // The card sits beneath the invocation URL, so pass a relative card path.
        A2ACardResolver resolver = new(runtimeUrl, http, agentCardPath: ".well-known/agent-card.json");

        // The agent publishes JSON-RPC interfaces only; ask for that binding explicitly.
        A2AClientOptions options = new() { PreferredBindings = [ProtocolBindingNames.JsonRpc] };

        return await resolver.GetAIAgentAsync(
            httpClient: http, options: options, cancellationToken: cancellationToken);
    }
}

// Usage:
//   AIAgent orderAgent = await OrderAgentClient.ConnectAsync(
//       runtimeUrl, new DefaultAzureCredential(), "api://order-agent/.default", ct);
//   Console.WriteLine(await orderAgent.RunAsync("Where is ORD-10042?", cancellationToken: ct));
