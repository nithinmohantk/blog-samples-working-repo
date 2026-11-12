using FhirEvents.Core;
using FhirEvents.Functions;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Npgsql;

static string Required(string name) =>
    Environment.GetEnvironmentVariable(name) is { Length: > 0 } value
        ? value
        : throw new InvalidOperationException($"Setting {name} is required.");

IHost host = new HostBuilder()
    .ConfigureFunctionsWorkerDefaults()
    .ConfigureServices(services =>
    {
        // One long-lived client. The connection lifetime makes it pick up DNS changes.
        HttpClient fhir = new(new SocketsHttpHandler { PooledConnectionLifetime = TimeSpan.FromMinutes(5) })
        {
            BaseAddress = new Uri(Required("FHIR_BASE_URL").TrimEnd('/') + "/"),
            Timeout = TimeSpan.FromSeconds(20),
        };
        services.AddSingleton<IFhirReader>(new HttpFhirReader(fhir));
        services.AddSingleton(NpgsqlDataSource.Create(Required("PROJECTION_DB")));
        services.AddSingleton<PostgresProjectionStore>();
        services.AddSingleton<IProjectionStore>(provider => provider.GetRequiredService<PostgresProjectionStore>());
        services.AddSingleton<FhirChangeHandler>();
    })
    .Build();

// Creating the table at start-up keeps the sample to one command. A real deployment runs migrations in its pipeline.
await host.Services.GetRequiredService<PostgresProjectionStore>().EnsureSchemaAsync(CancellationToken.None);
host.Run();
