using System.Text.Json.Nodes;

namespace AdtToFhir.Core;

public sealed record ProcessResult(string AckCode, string Ack, ApplyOutcome? Outcome, string Detail, IReadOnlyList<string> Notes, JsonObject? Sent);

/// <summary>One message in, one acknowledgement out: read, map, apply, and tell the sender what happened.</summary>
public sealed class AdtPipeline(AdtMapper mapper, FhirApplier applier, TimeProvider clock)
{
    private const int Attempts = 3;

    public async Task<ProcessResult> ProcessAsync(string text, CancellationToken cancel = default)
    {
        Hl7Message message;
        try { message = Hl7Message.Parse(text); }
        catch (Hl7ParseException error)
        {
            // Without a readable MSH there is nobody to address an acknowledgement to. The transport reports it.
            return new ProcessResult("AR", "", null, error.Message, [], null);
        }

        MapResult mapped;
        try { mapped = mapper.Map(message, clock.GetUtcNow()); }
        catch (MappingException error)
        {
            return new ProcessResult(error.AckCode, Ack.Build(message, error.AckCode, error.Message, clock.GetUtcNow()), null, error.Message, [], null);
        }

        ApplyResult result = new(ApplyOutcome.Failed, "not attempted", null);
        for (int attempt = 1; attempt <= Attempts; attempt++)
        {
            // Every attempt reads the server again, so a retry after a conflict decides on current facts.
            result = await applier.ApplyAsync(mapped, cancel);
            if (result.Outcome != ApplyOutcome.Conflict) { break; }
        }

        // Duplicate and Stale are answered AA on purpose: the message arrived and was dealt with, and a sender
        // that receives AE will send it again for ever. What was not applied is in Detail for the operator.
        (string code, string text) reply = result.Outcome switch
        {
            ApplyOutcome.Applied => ("AA", "applied"),
            ApplyOutcome.Duplicate => ("AA", $"not applied: {result.Detail}"),
            ApplyOutcome.Stale => ("AA", $"not applied: {result.Detail}"),
            _ => ("AE", result.Detail),
        };
        return new ProcessResult(reply.code, Ack.Build(message, reply.code, reply.text, clock.GetUtcNow()), result.Outcome, result.Detail, mapped.Notes, result.Sent);
    }
}
