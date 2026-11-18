using Amazon.Lambda.APIGatewayEvents;
using Amazon.Lambda.Core;
using Amazon.Lambda.RuntimeSupport;
using Amazon.Lambda.Serialization.SystemTextJson;
using Quotes;

// The same entry point for all three ways of publishing. On the managed runtime the handler setting is the
// assembly name, Quotes.Function; as Native AOT this program is the file named bootstrap that the OS-only
// runtime starts.
QuoteHandler handler = new();

// SnapStart, managed runtime only. Lambda calls the first hook before it takes the snapshot of an initialised
// environment and the second in every environment restored from it. Without SnapStart neither is called.
Amazon.Lambda.Core.SnapshotRestore.RegisterBeforeSnapshot(() =>
{
    handler.Warm();
    return ValueTask.CompletedTask;
});
Amazon.Lambda.Core.SnapshotRestore.RegisterAfterRestore(() =>
{
    handler.BecomeANewInstance();
    return ValueTask.CompletedTask;
});

await LambdaBootstrapBuilder
    .Create<APIGatewayHttpApiV2ProxyRequest, APIGatewayHttpApiV2ProxyResponse>(handler.Handle, new SourceGeneratorLambdaJsonSerializer<EventJson>())
    .Build()
    .RunAsync();
