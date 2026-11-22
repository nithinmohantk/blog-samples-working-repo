using System.Net;
using Microsoft.AspNetCore.Components;

namespace Desk.Client;

/// <summary>
/// When the web host answers 401 the session has ended. There is nothing to refresh in the browser,
/// because the browser holds no token: the only thing to do is to send the person to sign in again.
/// </summary>
public sealed class SessionHandler(NavigationManager navigation) : DelegatingHandler(new HttpClientHandler())
{
    protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
    {
        HttpResponseMessage response = await base.SendAsync(request, cancellationToken);
        if (response.StatusCode == HttpStatusCode.Unauthorized)
        {
            navigation.NavigateTo("signin", forceLoad: true);
        }

        return response;
    }
}
