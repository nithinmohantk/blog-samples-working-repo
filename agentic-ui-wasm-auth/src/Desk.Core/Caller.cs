namespace Desk.Core;

/// <summary>
/// The person on whose behalf a tool runs. It comes from the validated token on the request, never from
/// the conversation, so nothing the model reads or writes can change it.
/// </summary>
public sealed record Caller(string Subject, string Name, decimal RefundLimit)
{
    public static Caller None { get; } = new("", "", 0m);

    public bool IsKnown => Subject.Length > 0;
}
