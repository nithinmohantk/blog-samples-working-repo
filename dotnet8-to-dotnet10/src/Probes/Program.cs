// Runs the same code on whichever runtime the project was built for and prints one JSON object:
// probe name -> what was observed. upgrade_check.py runs it on .NET 8 and .NET 10 and compares.
using System.Diagnostics;
using System.Linq.Expressions;
using System.Net;
using System.Net.Mail;
using System.Runtime;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Xml.Serialization;
using Microsoft.AspNetCore.Authentication.Cookies;
using Microsoft.AspNetCore.Diagnostics;
using Microsoft.AspNetCore.Hosting.Server;
using Microsoft.AspNetCore.Hosting.Server.Features;

SortedDictionary<string, string> observed = new(StringComparer.Ordinal);

async Task Probe(string name, Func<Task<string>> probe)
{
    try { observed[name] = await probe(); }
    catch (Exception error) { observed[name] = $"threw {error.GetType().Name}"; }
}

// ---- ASP.NET Core ------------------------------------------------------------------------------------

await Probe("aspnet.cookie_auth_on_api_endpoint", async () =>
{
    WebApplicationBuilder builder = QuietBuilder();
    builder.Services.AddAuthentication(CookieAuthenticationDefaults.AuthenticationScheme).AddCookie();
    builder.Services.AddAuthorization();
    await using WebApplication app = builder.Build();
    app.UseAuthentication();
    app.UseAuthorization();
    app.MapGet("/api/orders", () => new Order(1, "open")).RequireAuthorization();
    await app.StartAsync();
    using HttpClient client = new(new HttpClientHandler { AllowAutoRedirect = false }) { BaseAddress = new Uri(Address(app)) };
    using HttpResponseMessage response = await client.GetAsync("/api/orders");
    return $"{(int)response.StatusCode}" + (response.Headers.Location is { } location ? $", Location {location.AbsolutePath}" : ", no Location header");
});

await Probe("aspnet.handled_exception_is_logged", async () =>
{
    CapturingLoggerProvider logs = new();
    WebApplicationBuilder builder = QuietBuilder();
    builder.Logging.AddProvider(logs).SetMinimumLevel(LogLevel.Information);
    builder.Services.AddExceptionHandler<HandlesEverything>();
    await using WebApplication app = builder.Build();
    app.UseExceptionHandler(_ => { });
    app.MapGet("/boom", string () => throw new InvalidOperationException("synthetic failure"));
    await app.StartAsync();
    using HttpClient client = new() { BaseAddress = new Uri(Address(app)) };
    using HttpResponseMessage response = await client.GetAsync("/boom");
    int errors = logs.Entries.Count(e => e.Level >= LogLevel.Error && e.Category.Contains("ExceptionHandlerMiddleware"));
    return $"{(int)response.StatusCode}, {errors} error log entr{(errors == 1 ? "y" : "ies")} from the middleware";
});

await Probe("aspnet.hostbuilder_validates_scopes_in_development", () =>
{
    try
    {
        using IHost host = new HostBuilder()
            .UseEnvironment("Development")
            .ConfigureWebHost(web => web.UseKestrel().UseUrls("http://127.0.0.1:0").Configure(_ => { }))
            .ConfigureServices(services => services.AddScoped<ScopedThing>().AddSingleton<NeedsScopedThing>())
            .Build();
        return Task.FromResult("built without complaint");
    }
    catch (Exception error)
    {
        return Task.FromResult($"refused at build: {error.GetType().Name}");
    }
});

// ---- Hosting and extensions --------------------------------------------------------------------------

await Probe("hosting.backgroundservice_sync_work_blocks_startup", async () =>
{
    using IHost host = new HostBuilder().ConfigureServices(s => s.AddHostedService<SlowToFirstAwait>()).Build();
    Stopwatch watch = Stopwatch.StartNew();
    await host.StartAsync();
    long elapsed = watch.ElapsedMilliseconds;
    await host.StopAsync();
    return elapsed >= 1000 ? "yes: StartAsync waited for it" : "no: StartAsync returned first";
});

await Probe("di.getkeyedservice_with_anykey", () =>
{
    ServiceCollection services = new();
    services.AddKeyedSingleton<IThing>(KeyedService.AnyKey, (_, _) => new Thing());
    using ServiceProvider provider = services.BuildServiceProvider();
    try { return Task.FromResult(provider.GetKeyedService<IThing>(KeyedService.AnyKey) is null ? "returned null" : "returned the AnyKey registration"); }
    catch (InvalidOperationException) { return Task.FromResult("threw InvalidOperationException"); }
});

await Probe("configuration.null_in_json", () =>
{
    const string json = """{ "Settings": { "Name": null, "Retries": null, "Hosts": [null, null] } }""";
    IConfiguration configuration = new ConfigurationBuilder().AddJsonStream(new MemoryStream(Encoding.UTF8.GetBytes(json))).Build();
    Settings settings = configuration.GetSection("Settings").Get<Settings>() ?? new Settings();
    string hosts = settings.Hosts is null ? "null" : "[" + string.Join(", ", settings.Hosts.Select(h => h is null ? "null" : $"'{h}'")) + "]";
    return Task.FromResult($"Name={(settings.Name is null ? "null" : $"'{settings.Name}'")}, Retries={settings.Retries?.ToString() ?? "null"}, Hosts={hosts}");
});

// ---- HttpClientFactory -------------------------------------------------------------------------------

await Probe("http.factory_primary_handler", () =>
{
    using ServiceProvider provider = new ServiceCollection().AddHttpClient().BuildServiceProvider();
    HttpMessageHandler handler = provider.GetRequiredService<IHttpMessageHandlerFactory>().CreateHandler("probe");
    while (handler is DelegatingHandler { InnerHandler: { } inner }) { handler = inner; }
    return Task.FromResult(handler.GetType().Name);
});

await Probe("http.factory_logs_header_values", async () =>
{
    await using WebApplication server = QuietBuilder().Build();
    server.MapGet("/", () => "ok");
    await server.StartAsync();
    CapturingLoggerProvider logs = new();
    using ServiceProvider provider = new ServiceCollection()
        .AddLogging(logging => logging.AddProvider(logs).SetMinimumLevel(LogLevel.Trace))
        .AddHttpClient().BuildServiceProvider();
    using HttpRequestMessage request = new(HttpMethod.Get, Address(server));
    request.Headers.Add("X-Api-Key", "synthetic-key-12345");
    using HttpResponseMessage response = await provider.GetRequiredService<IHttpClientFactory>().CreateClient("probe").SendAsync(request);
    bool named = logs.Entries.Any(e => e.Message.Contains("X-Api-Key"));
    bool leaked = logs.Entries.Any(e => e.Message.Contains("synthetic-key-12345"));
    return !named ? "header not logged" : leaked ? "value written to the log" : "value redacted";
});

// ---- Language and core libraries ---------------------------------------------------------------------

await Probe("language.array_contains_in_expression_tree", () =>
{
    Expression<Func<int[], int, bool>> contains = (values, wanted) => values.Contains(wanted);
    string bound = ((MethodCallExpression)contains.Body).Method.DeclaringType!.Name;
    string interpreted;
    try { interpreted = contains.Compile(preferInterpretation: true)(new[] { 1, 2, 3 }, 2) ? "interprets" : "interprets wrongly"; }
    catch (Exception error) { interpreted = $"interpreter throws {error.GetType().Name}"; }
    return Task.FromResult($"binds to {bound}.Contains, {interpreted}");
});

await Probe("runtime.float_to_int_out_of_range", () =>
{
    double huge = double.Parse("1e20", System.Globalization.CultureInfo.InvariantCulture);
    double nan = double.Parse("NaN", System.Globalization.CultureInfo.InvariantCulture);
    double negative = double.Parse("-1", System.Globalization.CultureInfo.InvariantCulture);
    return Task.FromResult($"(int)1e20={unchecked((int)huge)}, (int)NaN={unchecked((int)nan)}, (uint)-1.0={unchecked((uint)negative)}");
});

await Probe("runtime.empty_environment_variable", () =>
{
    Environment.SetEnvironmentVariable("PROBE_EMPTY", "");
    string? value = Environment.GetEnvironmentVariable("PROBE_EMPTY");
    return Task.FromResult(value is null ? "setting \"\" deletes the variable" : "setting \"\" keeps an empty variable");
});

await Probe("runtime.server_gc_adaptation_mode", () =>
{
    IReadOnlyDictionary<string, object> settings = GC.GetConfigurationVariables();
    string mode = settings.TryGetValue("GCDynamicAdaptationMode", out object? value) ? value.ToString()! : "not reported";
    return Task.FromResult($"server GC {(GCSettings.IsServerGC ? "on" : "off")}, GCDynamicAdaptationMode {mode}");
});

await Probe("serialization.binaryformatter_with_the_opt_in", () =>
{
    Type? type = Type.GetType("System.Runtime.Serialization.Formatters.Binary.BinaryFormatter, System.Runtime.Serialization.Formatters");
    if (type is null) { return Task.FromResult("type not found"); }
    try
    {
        object formatter = Activator.CreateInstance(type)!;
        using MemoryStream stream = new();
        type.GetMethod("Serialize", new[] { typeof(Stream), typeof(object) })!.Invoke(formatter, new object[] { stream, "payload" });
        return Task.FromResult("serializes");
    }
    catch (System.Reflection.TargetInvocationException error)
    {
        return Task.FromResult($"throws {error.InnerException!.GetType().Name}");
    }
});

await Probe("json.nullable_jsondocument_property", () =>
{
    Envelope envelope = JsonSerializer.Deserialize<Envelope>("""{"Body":null}""")!;
    return Task.FromResult(envelope.Body is null ? "null" : $"a JsonDocument of kind {envelope.Body.RootElement.ValueKind}");
});

await Probe("json.property_named_like_the_type_discriminator", () =>
{
    try { return Task.FromResult("serializes " + JsonSerializer.Serialize<Animal>(new Dog())); }
    catch (Exception error) { return Task.FromResult($"throws {error.GetType().Name}"); }
});

await Probe("net.uri_longer_than_65519", () =>
{
    try { return Task.FromResult($"accepted, {new Uri("https://example.org/" + new string('a', 70000)).AbsoluteUri.Length} characters"); }
    catch (UriFormatException) { return Task.FromResult("throws UriFormatException"); }
});

await Probe("net.mailaddress_consecutive_dots", () =>
{
    try { return Task.FromResult($"accepted {new MailAddress("first..last@example.org").Address}"); }
    catch (FormatException) { return Task.FromResult("throws FormatException"); }
});

await Probe("diagnostics.default_propagator_fields", () =>
    Task.FromResult(string.Join(", ", DistributedContextPropagator.Current.Fields.OrderBy(f => f, StringComparer.OrdinalIgnoreCase))));

await Probe("xml.obsolete_property_is_serialized", () =>
{
    using StringWriter writer = new();
    new XmlSerializer(typeof(Legacy)).Serialize(writer, new Legacy { Current = "a", Old = "b" });
    return Task.FromResult(writer.ToString().Contains("<Old>") ? "yes" : "no");
});

observed["_runtime"] = $"{Environment.Version}";
Console.WriteLine(JsonSerializer.Serialize(observed, new JsonSerializerOptions { WriteIndented = true }));
return 0;

static WebApplicationBuilder QuietBuilder()
{
    WebApplicationBuilder builder = WebApplication.CreateBuilder(new WebApplicationOptions { EnvironmentName = "Production" });
    builder.Logging.ClearProviders();
    builder.WebHost.UseUrls("http://127.0.0.1:0");
    return builder;
}

static string Address(WebApplication app) =>
    app.Services.GetRequiredService<IServer>().Features.Get<IServerAddressesFeature>()!.Addresses.First();

internal sealed record Order(int Id, string Status);

internal sealed class HandlesEverything : IExceptionHandler
{
    public async ValueTask<bool> TryHandleAsync(HttpContext httpContext, Exception exception, CancellationToken cancellationToken)
    {
        httpContext.Response.StatusCode = StatusCodes.Status500InternalServerError;
        await httpContext.Response.WriteAsJsonAsync(new { error = "handled" }, cancellationToken);
        return true;
    }
}

internal sealed class ScopedThing;

internal sealed class NeedsScopedThing(ScopedThing scoped)
{
    public ScopedThing Scoped { get; } = scoped;
}

internal sealed class SlowToFirstAwait : BackgroundService
{
    protected override Task ExecuteAsync(CancellationToken stoppingToken)
    {
        Thread.Sleep(1500); // stands for synchronous start-up work: loading a cache, opening a connection
        return Task.CompletedTask;
    }
}

internal interface IThing;

internal sealed class Thing : IThing;

internal sealed class Settings
{
    public string? Name { get; set; } = "default-name";
    public int? Retries { get; set; } = 3;
    public string[]? Hosts { get; set; }
}

internal sealed class Envelope
{
    public JsonDocument? Body { get; set; }
}

[JsonPolymorphic(TypeDiscriminatorPropertyName = "Type")]
[JsonDerivedType(typeof(Dog), "dog")]
internal abstract class Animal
{
    public abstract string Type { get; }
}

internal sealed class Dog : Animal
{
    public override string Type => "Dog";
}

public sealed class Legacy
{
    public string? Current { get; set; }

    [Obsolete("Use Current.")]
    public string? Old { get; set; }
}

internal sealed class CapturingLoggerProvider : ILoggerProvider
{
    public System.Collections.Concurrent.ConcurrentQueue<(string Category, LogLevel Level, string Message)> Entries { get; } = new();

    public ILogger CreateLogger(string categoryName) => new Capture(categoryName, Entries);

    public void Dispose() { }

    private sealed class Capture(string category, System.Collections.Concurrent.ConcurrentQueue<(string, LogLevel, string)> entries) : ILogger
    {
        public IDisposable? BeginScope<TState>(TState state) where TState : notnull => null;

        public bool IsEnabled(LogLevel logLevel) => true;

        public void Log<TState>(LogLevel logLevel, EventId eventId, TState state, Exception? exception, Func<TState, Exception?, string> formatter) =>
            entries.Enqueue((category, logLevel, formatter(state, exception)));
    }
}
