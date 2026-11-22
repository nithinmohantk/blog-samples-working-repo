using AGUI.Client;
using Desk.Client;
using Microsoft.AspNetCore.Components;
using Microsoft.AspNetCore.Components.WebAssembly.Hosting;
using Microsoft.Extensions.AI;

WebAssemblyHostBuilder builder = WebAssemblyHostBuilder.CreateDefault(args);

// Same origin, so the browser attaches the session cookie by itself. The header is the cross-site check.
builder.Services.AddScoped(services =>
{
    HttpClient http = new(new SessionHandler(services.GetRequiredService<NavigationManager>()))
    {
        BaseAddress = new Uri(builder.HostEnvironment.BaseAddress),
        Timeout = Timeout.InfiniteTimeSpan,
    };
    http.DefaultRequestHeaders.Add("X-Desk-Client", "1");
    return http;
});

// In the browser the AG-UI client is the page itself. It calls the web host, never the agent service.
builder.Services.AddScoped<IChatClient>(services => new AGUIChatClient(
    new AGUIChatClientOptions(services.GetRequiredService<HttpClient>(), "/agent")));

await builder.Build().RunAsync();
