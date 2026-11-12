using System.Text;
using FhirFacade;
using Microsoft.AspNetCore.Authentication.JwtBearer;
using Microsoft.IdentityModel.Tokens;

WebApplicationBuilder builder = WebApplication.CreateBuilder(args);

AuthOptions auth = builder.Configuration.GetSection("Auth").Get<AuthOptions>() ?? new AuthOptions();
bool useDevelopmentKey = !string.IsNullOrEmpty(auth.DevelopmentSigningSecret);
if (string.IsNullOrEmpty(auth.Audience))
{
    throw new InvalidOperationException("Auth:Audience is required.");
}

if (useDevelopmentKey && !builder.Environment.IsDevelopment())
{
    throw new InvalidOperationException("Auth:DevelopmentSigningSecret is only honoured in the Development environment.");
}

if (!useDevelopmentKey && string.IsNullOrEmpty(auth.Authority))
{
    throw new InvalidOperationException("Auth:Authority is required.");
}

builder.Services.AddAuthentication(JwtBearerDefaults.AuthenticationScheme).AddJwtBearer(options =>
{
    // Keep the claim names as issued ("scp", "roles", "fhirUser") instead of the legacy WS-* names.
    options.MapInboundClaims = false;
    options.Audience = auth.Audience;

    if (useDevelopmentKey)
    {
        // Local testing without an identity provider: tokens signed with a shared secret by the test client.
        options.TokenValidationParameters = new TokenValidationParameters
        {
            ValidIssuer = auth.DevelopmentIssuer,
            ValidAudience = auth.Audience,
            IssuerSigningKey = new SymmetricSecurityKey(Encoding.UTF8.GetBytes(auth.DevelopmentSigningSecret!)),
            ValidAlgorithms = [SecurityAlgorithms.HmacSha256],
        };
    }
    else
    {
        // Signing keys and the issuer come from the authority's OpenID Connect metadata.
        options.Authority = auth.Authority;
        options.TokenValidationParameters.ValidAlgorithms = [SecurityAlgorithms.RsaSha256];
    }
});

builder.Services.AddFacade(builder.Configuration);

WebApplication app = builder.Build();
app.MapFacade();
app.Run();
