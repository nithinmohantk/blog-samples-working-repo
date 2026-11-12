#pragma warning disable OPENAI001 // The constructor that takes an authentication policy is marked experimental.
using System.ClientModel;
using System.ClientModel.Primitives;
using Azure.Identity;
using ClinicalCoding.Core;
using OpenAI;
using OpenAI.Chat;

namespace ClinicalCoding.AzureOpenAI;

/// <summary>Asks an Azure OpenAI deployment for findings in the shape of the extraction schema, and nothing else.</summary>
public sealed class AzureOpenAIExtractor
{
    public const string SchemaName = "clinical_findings";

    private readonly ChatClient _client;
    private readonly CodingSubset _subset;
    private readonly ChatCompletionOptions _options;

    /// <param name="endpoint">The resource endpoint, for example https://my-resource.openai.azure.com</param>
    /// <param name="deployment">The model deployment name.</param>
    public AzureOpenAIExtractor(Uri endpoint, string deployment, CodingSubset subset)
    {
        // Microsoft Entra ID, not an API key: the identity running this code needs the Cognitive Services OpenAI User role.
        BearerTokenPolicy tokenPolicy = new(new DefaultAzureCredential(), "https://ai.azure.com/.default");
        _client = new ChatClient(
            model: deployment,
            authenticationPolicy: tokenPolicy,
            options: new OpenAIClientOptions
            {
                Endpoint = new Uri(endpoint, "/openai/v1"),
                NetworkTimeout = TimeSpan.FromSeconds(60),
            });
        _subset = subset;
        _options = new ChatCompletionOptions
        {
            ResponseFormat = ChatResponseFormat.CreateJsonSchemaFormat(
                jsonSchemaFormatName: SchemaName,
                jsonSchema: BinaryData.FromString(ExtractionSchema.Build(subset).ToJsonString()),
                jsonSchemaIsStrict: true),
        };
    }

    /// <summary>Returns proposals for a reviewer. Throws <see cref="ShapeException"/> when the response cannot be used.</summary>
    public async Task<IReadOnlyList<Proposal>> ProposeAsync(string noteText, CancellationToken cancellationToken)
    {
        ChatCompletion completion;
        try
        {
            ClientResult<ChatCompletion> result = await _client.CompleteChatAsync(
                [new SystemChatMessage(ExtractionSchema.SystemPrompt(_subset)), new UserChatMessage(noteText)],
                _options, cancellationToken).ConfigureAwait(false);
            completion = result.Value;
        }
        catch (ClientResultException ex)
        {
            // Status only. The message can echo request content, and the request is a clinical note.
            throw new InvalidOperationException($"The model call failed with HTTP status {ex.Status}.");
        }

        // A response cut off by the token limit or a content filter is not a short answer: it is no answer.
        if (completion.FinishReason != ChatFinishReason.Stop)
        {
            throw new ShapeException($"the response did not complete: {completion.FinishReason}");
        }

        if (!string.IsNullOrEmpty(completion.Refusal))
        {
            throw new ShapeException("the model refused the request");
        }

        if (completion.Content.Count != 1)
        {
            throw new ShapeException("the response has no single text part");
        }

        Extraction extraction = ResponseGuard.Parse(completion.Content[0].Text, _subset);
        return ResponseGuard.Check(extraction, noteText, _subset);
    }
}
