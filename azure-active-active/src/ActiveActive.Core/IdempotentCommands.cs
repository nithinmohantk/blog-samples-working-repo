using System.Collections.Concurrent;

namespace ActiveActive.Core;

/// <summary>The stored outcome of a command, returned again when the same command is retried.</summary>
public sealed record CommandOutcome(int StatusCode, string Body, string Region);

/// <summary>
/// Makes a retried request safe. A client that times out against one region and retries against the other
/// sends the same idempotency key; the command runs once and both attempts get the same answer.
/// In production the store is the regional database (the key is written in the same transaction as the
/// booking), not process memory.
/// </summary>
public sealed class IdempotentCommands
{
    private readonly ConcurrentDictionary<string, Lazy<CommandOutcome>> _outcomes = new(StringComparer.Ordinal);

    /// <summary>Runs <paramref name="command"/> at most once per key, even under concurrent calls.</summary>
    public CommandOutcome Execute(string idempotencyKey, Func<CommandOutcome> command)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(idempotencyKey);
        return _outcomes.GetOrAdd(idempotencyKey, _ => new Lazy<CommandOutcome>(command, LazyThreadSafetyMode.ExecutionAndPublication)).Value;
    }

    /// <summary>Applies outcomes replicated from another region, so a retry that lands here is recognised.</summary>
    public void Import(string idempotencyKey, CommandOutcome outcome) =>
        _outcomes.TryAdd(idempotencyKey, new Lazy<CommandOutcome>(() => outcome));
}
