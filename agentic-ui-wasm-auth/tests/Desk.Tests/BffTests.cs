using System.Net;
using System.Text;
using AGUI.Client;
using Desk.Agent;
using Desk.Bff;
using Desk.Core;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.AspNetCore.TestHost;
using Microsoft.Extensions.AI;
using Microsoft.Extensions.DependencyInjection;
using Xunit;

namespace Desk.Tests;

/// <summary>
/// The web host in front of the agent service, both on in-memory servers. The test client keeps
/// cookies the way a browser does, and never sees a token.
/// </summary>
public sealed class BffTests : IDisposable
{
    private readonly WebApplicationFactory<AgentService> _agent;
    private readonly WebApplicationFactory<BffService> _bff;
    private readonly Ledger _ledger;
    private readonly WireLog _wire;

    public BffTests()
    {
        _agent = new WebApplicationFactory<AgentService>().WithWebHostBuilder(host => host.UseSetting("DESK_WORD_DELAY_MS", "0"));
        _ledger = _agent.Services.GetRequiredService<Ledger>();
        _wire = _agent.Services.GetRequiredService<WireLog>();
        _bff = new WebApplicationFactory<BffService>().WithWebHostBuilder(host => host
            .UseSetting("DESK_LAB", "true")
            .ConfigureTestServices(services => services.AddHttpClient("agent").ConfigurePrimaryHttpMessageHandler(() => _agent.Server.CreateHandler())));
    }

    public void Dispose()
    {
        _bff.Dispose();
        _agent.Dispose();
    }

    [Fact]
    public async Task Without_a_session_the_page_redirects_to_sign_in_and_the_endpoint_answers_401()
    {
        using HttpClient browser = Browser();
        using HttpResponseMessage page = await browser.GetAsync("/");
        using HttpResponseMessage me = await browser.GetAsync("/bff/me");
        using HttpResponseMessage run = await PostAsync(browser, "{}", withHeader: true);

        Trace.Line("auth-results.txt", $"web host, no session | GET / HTTP {(int)page.StatusCode} to {page.Headers.Location?.PathAndQuery} | GET /bff/me HTTP {(int)me.StatusCode} | POST /agent HTTP {(int)run.StatusCode}");
        Assert.Equal(HttpStatusCode.Redirect, page.StatusCode);
        Assert.StartsWith("/signin", page.Headers.Location!.PathAndQuery);
        Assert.Equal(HttpStatusCode.Unauthorized, me.StatusCode);
        Assert.Equal(HttpStatusCode.Unauthorized, run.StatusCode);
        Assert.Empty(_wire.Entries);
    }

    [Fact]
    public async Task The_session_cookie_is_HttpOnly_and_SameSite_Strict()
    {
        using HttpClient browser = Browser();
        using HttpResponseMessage response = await browser.PostAsync("/signin", new FormUrlEncodedContent([new("user", "sam")]));
        string cookie = string.Join("; ", response.Headers.GetValues("Set-Cookie"));

        Trace.Line("auth-results.txt", $"web host, sign-in | Set-Cookie attributes: {string.Join("; ", cookie.Split("; ").Skip(1))}");
        Assert.Contains("httponly", cookie, StringComparison.OrdinalIgnoreCase);
        Assert.Contains("samesite=strict", cookie, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public async Task An_unknown_user_cannot_sign_in()
    {
        using HttpClient browser = Browser();
        using HttpResponseMessage response = await browser.PostAsync("/signin", new FormUrlEncodedContent([new("user", "mallory")]));
        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
    }

    [Fact]
    public async Task With_a_session_but_without_the_client_header_the_request_is_refused()
    {
        using HttpClient browser = await SignedInAsync("sam");
        using HttpResponseMessage response = await PostAsync(browser, "{}", withHeader: false);

        Trace.Line("auth-results.txt", $"web host, session, no X-Desk-Client header | POST /agent HTTP {(int)response.StatusCode}");
        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
        Assert.Empty(_wire.Entries);
    }

    [Fact]
    public async Task With_a_session_the_stream_comes_through_and_the_refund_is_recorded_against_the_person()
    {
        using HttpClient browser = await SignedInAsync("sam");
        browser.DefaultRequestHeaders.Add(AgentForwarder.ClientHeader, "1");
        IChatClient chat = new AGUIChatClient(new AGUIChatClientOptions(browser, "/agent"));

        List<ChatMessage> messages = [new(ChatRole.User, "Refund order O-1003")];
        List<ChatResponseUpdate> first = await ToListAsync(chat.GetStreamingResponseAsync(messages, new ChatOptions { ConversationId = "t-bff" }));
        ToolApprovalRequestContent request = first.SelectMany(update => update.Contents).OfType<ToolApprovalRequestContent>().Single();
        messages.Add(new(ChatRole.Assistant, [request]));
        messages.Add(new(ChatRole.User, [request.CreateResponse(true)]));
        await ToListAsync(chat.GetStreamingResponseAsync(messages, new ChatOptions { ConversationId = "t-bff" }));

        Refund refund = Assert.Single(_ledger.Refunds);
        Trace.Line("auth-results.txt", $"through the web host as sam | refund {refund.OrderId} {refund.Amount:0.00} approvedBy={refund.ApprovedBy} | requests seen by the agent service: {_wire.Entries.Count}");
        Assert.Equal("sam", refund.ApprovedBy);
        Assert.Equal(2, _wire.Entries.Count);
    }

    [Fact]
    public async Task Stopping_in_the_browser_ends_the_run_on_the_agent_service()
    {
        using HttpClient browser = await SignedInAsync("sam");
        browser.DefaultRequestHeaders.Add(AgentForwarder.ClientHeader, "1");
        IChatClient chat = new AGUIChatClient(new AGUIChatClientOptions(browser, "/agent"));
        using CancellationTokenSource stop = new();
        int seen = 0;

        await Assert.ThrowsAnyAsync<OperationCanceledException>(async () =>
        {
            await foreach (ChatResponseUpdate update in chat.GetStreamingResponseAsync([new(ChatRole.User, "Explain the refund policy")], cancellationToken: stop.Token))
            {
                if (update.Text.Length > 0 && ++seen == 3)
                {
                    stop.Cancel();
                }
            }
        });

        for (int i = 0; i < 100 && _wire.Entries.Count == 0; i++)
        {
            await Task.Delay(50);
        }

        WireEntry entry = Assert.Single(_wire.Entries);
        Trace.Line("auth-results.txt", $"stop through the web host | agent service stream completed: {entry.Completed}, events sent: {entry.Events.Count}, RUN_FINISHED sent: {entry.Events.Contains("RUN_FINISHED")}");
        Assert.False(entry.Completed);
        Assert.DoesNotContain("RUN_FINISHED", entry.Events);
    }

    private HttpClient Browser() => _bff.CreateClient(new WebApplicationFactoryClientOptions { AllowAutoRedirect = false, HandleCookies = true });

    private async Task<HttpClient> SignedInAsync(string user)
    {
        HttpClient browser = Browser();
        using HttpResponseMessage response = await browser.PostAsync("/signin", new FormUrlEncodedContent([new("user", user)]));
        Assert.Equal(HttpStatusCode.Redirect, response.StatusCode);
        return browser;
    }

    private static async Task<HttpResponseMessage> PostAsync(HttpClient browser, string body, bool withHeader)
    {
        using HttpRequestMessage request = new(HttpMethod.Post, "/agent") { Content = new StringContent(body, Encoding.UTF8, "application/json") };
        if (withHeader)
        {
            request.Headers.Add(AgentForwarder.ClientHeader, "1");
        }

        return await browser.SendAsync(request);
    }

    private static async Task<List<ChatResponseUpdate>> ToListAsync(IAsyncEnumerable<ChatResponseUpdate> updates)
    {
        List<ChatResponseUpdate> list = [];
        await foreach (ChatResponseUpdate update in updates)
        {
            list.Add(update);
        }

        return list;
    }
}
