// Per-endpoint OpenAPI metadata through WithOpenApi.
WebApplication app = WebApplication.CreateBuilder(args).Build();
app.MapGet("/orders/{id}", (int id) => Results.Ok(id)).WithOpenApi();
Console.WriteLine("configured");
