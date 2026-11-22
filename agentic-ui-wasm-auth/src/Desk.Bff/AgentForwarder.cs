using System.Net.Http.Headers;
using System.Security.Claims;
using Desk.Core;
using Microsoft.AspNetCore.Http.Features;

namespace Desk.Bff;

/// <summary>
/// The only way from the browser to the agent service. The browser sends its session cookie; this
/// swaps it for a short-lived token addressed to the agent, and passes the event stream back as it arrives.
/// </summary>
public static class AgentForwarder
{
    /// <summary>A browser cannot add this header to a cross-site form post, so a page on another site cannot use the cookie.</summary>
    public const string ClientHeader = "X-Desk-Client";

    public static async Task ForwardAsync(HttpContext http, IHttpClientFactory clients, LabTokenIssuer tokens)
    {
        if (!http.Request.Headers.ContainsKey(ClientHeader) || http.Request.ContentType?.StartsWith("application/json", StringComparison.OrdinalIgnoreCase) != true)
        {
            http.Response.StatusCode = StatusCodes.Status400BadRequest;
            return;
        }

        ClaimsPrincipal user = http.User;
        using HttpRequestMessage request = new(HttpMethod.Post, "/agent") { Content = new StreamContent(http.Request.Body) };
        request.Content.Headers.ContentType = new MediaTypeHeaderValue("application/json");
        request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", tokens.Issue(
            user.FindFirstValue("sub")!, user.FindFirstValue("name")!, user.FindAll("roles").Select(role => role.Value)));

        // RequestAborted is what carries a Stop click from the browser on to the agent service.
        using HttpResponseMessage response = await clients.CreateClient("agent").SendAsync(request, HttpCompletionOption.ResponseHeadersRead, http.RequestAborted);
        http.Response.StatusCode = (int)response.StatusCode;
        http.Response.ContentType = response.Content.Headers.ContentType?.ToString();
        http.Response.Headers.CacheControl = "no-cache,no-store";
        http.Features.Get<IHttpResponseBodyFeature>()?.DisableBuffering();

        await using Stream upstream = await response.Content.ReadAsStreamAsync(http.RequestAborted);
        byte[] buffer = new byte[8192];
        int read;
        while ((read = await upstream.ReadAsync(buffer, http.RequestAborted)) > 0)
        {
            await http.Response.Body.WriteAsync(buffer.AsMemory(0, read), http.RequestAborted);
            await http.Response.Body.FlushAsync(http.RequestAborted);
        }
    }
}
