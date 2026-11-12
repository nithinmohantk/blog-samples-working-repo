using Amazon.BedrockRuntime;
using Azure.AI.OpenAI;
using Azure.Identity;
using Microsoft.Extensions.AI;
using TwoClouds.Chat;

var builder = WebApplication.CreateBuilder(args);
var config = builder.Configuration;

builder.Services.AddDistributedMemoryCache();   // use Redis once you run more than one instance
builder.Services.AddSingleton<IAmazonBedrockRuntime>(_ => new AmazonBedrockRuntimeClient());
builder.Services.AddSingleton<OrderTools>();

// One keyed client per provider. Model identity and credentials live in configuration
// and in the workload's identity, never in code.
builder.Services
    .AddKeyedChatClient("azure", _ =>
        new AzureOpenAIClient(new Uri(config["Chat:Azure:Endpoint"]!), new DefaultAzureCredential())
            .GetChatClient(config["Chat:Azure:Deployment"]!)
            .AsIChatClient())
    .UseProviderPipeline("azure");

builder.Services
    .AddKeyedChatClient("bedrock", services =>
        services.GetRequiredService<IAmazonBedrockRuntime>()
            .AsIChatClient(config["Chat:Bedrock:ModelId"]!))
    .UseProviderPipeline("bedrock");

// The client the application sees: a bounded tool loop over a failover pair.
string primary = config["Chat:Primary"] ?? "azure";
string secondary = primary == "azure" ? "bedrock" : "azure";

builder.Services
    .AddChatClient(services => new FailoverChatClient(
        services.GetRequiredKeyedService<IChatClient>(primary),
        services.GetRequiredKeyedService<IChatClient>(secondary),
        ProviderErrors.IsTransient,
        services.GetRequiredService<ILogger<FailoverChatClient>>()))
    .UseFunctionInvocation(configure: invoker => invoker.MaximumIterationsPerRequest = 5);

var app = builder.Build();

app.MapPost("/chat", async (ChatRequest request, IChatClient chat, OrderTools tools, CancellationToken cancellationToken) =>
{
    if (string.IsNullOrWhiteSpace(request.Message) || request.Message.Length > 4000)
    {
        return Results.BadRequest(new { message = "message must be between 1 and 4000 characters" });
    }

    ChatResponse response = await chat.GetResponseAsync(
        [
            new ChatMessage(ChatRole.System, "You answer order enquiries briefly. Use the tool for order status."),
            new ChatMessage(ChatRole.User, request.Message),
        ],
        new ChatOptions
        {
            MaxOutputTokens = 800,
            Temperature = 0.2f,
            Tools = [AIFunctionFactory.Create(tools.GetOrderStatus)],
        },
        cancellationToken);

    return Results.Ok(new
    {
        text = response.Text,
        inputTokens = response.Usage?.InputTokenCount,
        outputTokens = response.Usage?.OutputTokenCount,
    });
});

app.Run();

public sealed record ChatRequest(string Message);
