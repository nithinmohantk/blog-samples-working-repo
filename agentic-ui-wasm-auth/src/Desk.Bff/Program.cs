using System.Security.Claims;
using Desk.Bff;
using Desk.Bff.Components;
using Desk.Core;
using Microsoft.AspNetCore.Authentication;
using Microsoft.AspNetCore.Authentication.Cookies;

WebApplicationBuilder builder = WebApplication.CreateBuilder(args);
bool lab = builder.Configuration.GetValue("DESK_LAB", false);

builder.Services.AddRazorComponents().AddInteractiveWebAssemblyComponents();

// The session is a cookie the page's code cannot read. No token is ever given to the browser.
builder.Services.AddAuthentication(CookieAuthenticationDefaults.AuthenticationScheme).AddCookie(options =>
{
    options.Cookie.Name = "desk.session";
    options.Cookie.HttpOnly = true;
    options.Cookie.SameSite = SameSiteMode.Strict;
    options.Cookie.SecurePolicy = lab ? CookieSecurePolicy.SameAsRequest : CookieSecurePolicy.Always; // the lab runs on http://127.0.0.1
    options.ExpireTimeSpan = TimeSpan.FromMinutes(builder.Configuration.GetValue("DESK_SESSION_MINUTES", 30));
    options.SlidingExpiration = false;
    options.LoginPath = "/signin";

    // A page gets a redirect to the sign-in page. A call from code gets a plain 401 it can act on.
    options.Events.OnRedirectToLogin = context =>
    {
        if (context.Request.Path.StartsWithSegments("/agent") || context.Request.Path.StartsWithSegments("/bff"))
        {
            context.Response.StatusCode = StatusCodes.Status401Unauthorized;
        }
        else
        {
            context.Response.Redirect(context.RedirectUri);
        }

        return Task.CompletedTask;
    };
});
builder.Services.AddAuthorization();

builder.Services.AddHttpClient("agent", client =>
{
    client.BaseAddress = new Uri(builder.Configuration["AGENT_URL"] ?? "http://localhost:5101");
    client.Timeout = Timeout.InfiniteTimeSpan; // a streamed answer has no useful overall time limit
});
builder.Services.AddSingleton(new LabTokenIssuer(
    builder.Configuration["DESK_TOKEN_KEY"] ?? LabTokenIssuer.FakeKey,
    TimeSpan.FromSeconds(builder.Configuration.GetValue("DESK_TOKEN_SECONDS", 120))));

WebApplication app = builder.Build();

app.UseAuthentication();
app.UseAuthorization();
app.UseAntiforgery();
app.MapStaticAssets();

app.MapGet("/signin", () => Results.Content(LabUsers.SignInPage, "text/html"));
app.MapPost("/signin", async (HttpContext http) =>
{
    IFormCollection form = await http.Request.ReadFormAsync();
    if (LabUsers.Find(form["user"]) is not { } user)
    {
        return Results.BadRequest();
    }

    await http.SignInAsync(CookieAuthenticationDefaults.AuthenticationScheme, user);
    return Results.Redirect("/");
}).DisableAntiforgery();
app.MapPost("/signout", async (HttpContext http) =>
{
    await http.SignOutAsync(CookieAuthenticationDefaults.AuthenticationScheme);
    return Results.Redirect("/signin");
}).DisableAntiforgery();

app.MapGet("/bff/me", (ClaimsPrincipal user) => Results.Json(new
{
    name = user.FindFirstValue("name"),
    roles = user.FindAll("roles").Select(role => role.Value),
})).RequireAuthorization();

app.MapPost("/agent", AgentForwarder.ForwardAsync).RequireAuthorization();

app.MapRazorComponents<App>()
    .AddInteractiveWebAssemblyRenderMode()
    .AddAdditionalAssemblies(typeof(Desk.Client.Routes).Assembly)
    .RequireAuthorization();

await app.RunAsync();
