using System.ClientModel;
using System.Diagnostics.Metrics;
using Amazon.BedrockRuntime.Model;
using Microsoft.Extensions.AI;

namespace TwoClouds.Chat;

public static class ChatPipelineExtensions
{
    public const string TelemetrySourceName = "TwoClouds.Chat";

    /// <summary>The per-provider pipeline. The first call is the outermost layer.</summary>
    public static ChatClientBuilder UseProviderPipeline(this ChatClientBuilder builder, string provider) =>
        builder
            .UseOpenTelemetry(
                sourceName: TelemetrySourceName,
                configure: telemetry => telemetry.EnableSensitiveData = false)
            // The cache key is built from messages and options. It does not know which
            // provider answered, so add the provider or two clouds will share entries.
            .UseDistributedCache(configure: cache => cache.CacheKeyAdditionalValues = [provider])
            .Use((inner, services) => new UsageMeteringChatClient(
                inner, services.GetRequiredService<IMeterFactory>(), provider));
}

public static class ProviderErrors
{
    /// <summary>Errors worth retrying on another provider. Exception types are not unified by the abstraction.</summary>
    public static bool IsTransient(Exception exception) => exception switch
    {
        ThrottlingException or ServiceUnavailableException or ModelTimeoutException => true,
        ClientResultException { Status: 429 or >= 500 } => true,
        HttpRequestException or TimeoutException => true,
        _ => false,
    };
}
