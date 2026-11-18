using AGUI.Client;
using Desk.Web.Components;
using Microsoft.Extensions.AI;

WebApplicationBuilder builder = WebApplication.CreateBuilder(args);

builder.Services.AddRazorComponents().AddInteractiveServerComponents();

builder.Services.AddHttpClient("agent", client =>
{
    client.BaseAddress = new Uri(builder.Configuration["AGENT_URL"] ?? "http://localhost:5101");
    client.Timeout = Timeout.InfiniteTimeSpan; // a streamed answer has no useful overall time limit
});

// The UI does not know there is a model. It has a chat client that speaks AG-UI to the agent service.
builder.Services.AddScoped<IChatClient>(services => new AGUIChatClient(
    new AGUIChatClientOptions(services.GetRequiredService<IHttpClientFactory>().CreateClient("agent"), "/agent")));

WebApplication app = builder.Build();

app.MapStaticAssets();
app.MapRazorComponents<App>().AddInteractiveServerRenderMode();

await app.RunAsync();
