using AGUI.Abstractions;
using AGUI.Formatting;
using Microsoft.AspNetCore.Http.Features;

namespace Desk.Agent;

/// <summary>Writes AG-UI events to the response as Server-Sent Events, one event at a time, unbuffered.</summary>
public sealed class EventStreamResult(IAsyncEnumerable<BaseEvent> events) : IResult
{
    private static readonly SseEventStreamFormatter s_formatter = new();

    public async Task ExecuteAsync(HttpContext httpContext)
    {
        HttpResponse response = httpContext.Response;
        response.ContentType = s_formatter.MediaType;
        response.Headers.CacheControl = "no-cache,no-store";
        httpContext.Features.Get<IHttpResponseBodyFeature>()?.DisableBuffering();

        // RequestAborted fires when the browser side stops listening. Passing it on is what
        // turns a Stop button into a cancelled model call.
        await s_formatter.WriteAsync(events, response.Body, httpContext.RequestAborted);
        await response.Body.FlushAsync(httpContext.RequestAborted);
    }
}
