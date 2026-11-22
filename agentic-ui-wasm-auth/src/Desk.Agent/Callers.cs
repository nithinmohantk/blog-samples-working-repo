using System.Security.Claims;
using Desk.Core;

namespace Desk.Agent;

/// <summary>Turns the validated token into the person the tools act for. Roles decide the refund limit.</summary>
public static class Callers
{
    public const string Policy = "desk.use";
    public const decimal AgentLimit = 40.00m;

    public static Caller From(ClaimsPrincipal? user)
    {
        if (user?.Identity?.IsAuthenticated != true || user.FindFirstValue("sub") is not { Length: > 0 } subject)
        {
            return Caller.None;
        }

        decimal limit = user.IsInRole("supervisor") ? decimal.MaxValue : user.IsInRole("agent") ? AgentLimit : 0m;
        return new Caller(subject, user.FindFirstValue("name") ?? subject, limit);
    }
}
