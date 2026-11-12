// Program.cs - the same resource-server rules in ASP.NET Core, with Microsoft Entra ID as the issuer.
// NOT COMPILED by the author. Based on the ProtectedMcpServer sample at tag v1.4.0 of the MCP C# SDK.
//
//   dotnet add package ModelContextProtocol.AspNetCore --version 1.4.0
//   dotnet add package Microsoft.AspNetCore.Authentication.JwtBearer
using System.ComponentModel;
using Microsoft.AspNetCore.Authentication.JwtBearer;
using Microsoft.AspNetCore.Authorization;
using Microsoft.IdentityModel.Tokens;
using ModelContextProtocol.AspNetCore.Authentication;
using ModelContextProtocol.Server;

var builder = WebApplication.CreateBuilder(args);

string Required(string key) =>
    builder.Configuration[key] ?? throw new InvalidOperationException($"{key} is not configured");

string tenantId = Required("Mcp:TenantId");
string clientId = Required("Mcp:ClientId");          // the app registration that represents THIS server
string resourceUrl = Required("Mcp:ResourceUrl");    // the public URL clients use
string authority = $"https://login.microsoftonline.com/{tenantId}/v2.0";

builder.Services
    .AddAuthentication(options =>
    {
        options.DefaultAuthenticateScheme = JwtBearerDefaults.AuthenticationScheme;
        // The MCP scheme writes the 401 challenge and serves the protected resource metadata.
        options.DefaultChallengeScheme = McpAuthenticationDefaults.AuthenticationScheme;
    })
    .AddJwtBearer(options =>
    {
        options.Authority = authority;
        options.MapInboundClaims = false;            // keep the claim name "scp" as issued
        options.TokenValidationParameters = new TokenValidationParameters
        {
            ValidateIssuer = true,
            ValidIssuer = authority,
            ValidateAudience = true,
            ValidAudiences = [clientId, $"api://{clientId}"],   // v2 and v1 token formats
            ValidateLifetime = true,
            ValidateIssuerSigningKey = true,
            ValidAlgorithms = [SecurityAlgorithms.RsaSha256],
            ClockSkew = TimeSpan.FromSeconds(30),
        };
    })
    .AddMcp(options =>
    {
        options.ResourceMetadata = new()
        {
            Resource = resourceUrl,
            AuthorizationServers = { authority },
            ScopesSupported = [$"api://{clientId}/orders.read"],
        };
    });

builder.Services.AddAuthorizationBuilder()
    .AddPolicy("orders.read", p => p.RequireAuthenticatedUser().RequireAssertion(c => HasScope(c, "orders.read")))
    .AddPolicy("orders.write", p => p.RequireAuthenticatedUser().RequireAssertion(c => HasScope(c, "orders.write")));

builder.Services.AddMcpServer()
    .WithHttpTransport(options => options.Stateless = true)   // no session affinity
    .AddAuthorizationFilters()                                 // honours [Authorize] on individual tools
    .WithTools<OrderTools>();

var app = builder.Build();

app.UseAuthentication();
app.UseAuthorization();

app.MapGet("/healthz", () => Results.Ok()).AllowAnonymous();
app.MapMcp("/mcp").RequireAuthorization("orders.read");       // coarse scope on every request

app.Run();

static bool HasScope(AuthorizationHandlerContext context, string scope) =>
    (context.User.FindFirst("scp")?.Value ?? string.Empty)
        .Split(' ', StringSplitOptions.RemoveEmptyEntries)
        .Contains(scope);

[McpServerToolType]
public sealed class OrderTools
{
    [McpServerTool, Description("Return the fulfilment status of one order. orderId looks like ORD-10042.")]
    public static object GetOrderStatus(string orderId) =>
        new { orderId = Validate(orderId), status = "SHIPPED" };

    [McpServerTool, Description("Cancel one order. Irreversible. orderId looks like ORD-10042.")]
    [Authorize(Policy = "orders.write")]                       // per-tool scope
    public static object CancelOrder(string orderId) =>
        new { orderId = Validate(orderId), status = "CANCELLED" };

    private static string Validate(string orderId) =>
        System.Text.RegularExpressions.Regex.IsMatch(orderId, @"^ORD-\d{3,10}$")
            ? orderId
            : throw new ArgumentException("orderId must look like ORD-10042");
}
