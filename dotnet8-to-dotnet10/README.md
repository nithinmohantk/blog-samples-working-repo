# Moving an API from .NET 8 to .NET 10

Sample for the dataa.dev article "[Moving a .NET 8 API to .NET 10: What Breaks Between Two LTS Releases](https://www.dataa.dev/2026/02/07/moving-a-dotnet-8-api-to-dotnet-10-what-breaks-between-two-lts-releases/)".

The same code built and run three ways, with every difference recorded:

| Leg | SDK | Target | What it stands for |
| --- | --- | --- | --- |
| A | 8.0.417 | `net8.0` (runtime 8.0.23) | Where the service is today |
| B | 10.0.102 | `net8.0` (runtime 8.0.23) | Step one: new SDK, same runtime |
| C | 10.0.102 | `net10.0` (runtime 10.0.2) | Step two: new target |

| Path | What it is |
| --- | --- |
| `src/Probes` | One multi-targeted ASP.NET Core project. Twenty probes of runtime behaviour, printed as JSON |
| `compile/` | Nine small projects of ordinary older code. The script records what the build says about each |
| `upgrade_check.py` | Builds and runs everything on each leg and compares |
| `recorded.json` | The results below. The CI run fails if an observation stops matching |
| `ci.sh` | Installs both SDKs into private directories and runs the check |

## Run

    ./ci.sh out        # needs curl, Python 3 and Docker; downloads the SDKs itself

## What was verified

GitHub Actions, `ubuntu-latest`, with the SDKs installed by `dotnet-install.sh` into private directories so
nothing rolls forward to a newer runtime on the machine. 28 of 29 observations differ between the legs; only
one of them (`dotnet new sln`) changes at leg B.

| Observation | A: SDK 8, net8.0 | B: SDK 10, net8.0 | C: SDK 10, net10.0 |
| --- | --- | --- | --- |
| `aspnet.cookie_auth_on_api_endpoint` | 302, Location /Account/Login | 302, Location /Account/Login | 401, Location /Account/Login |
| `aspnet.handled_exception_is_logged` | 500, 1 error log entry from the middleware | 500, 1 error log entry from the middleware | 500, 0 error log entries from the middleware |
| `aspnet.hostbuilder_validates_scopes_in_development` | built without complaint | built without complaint | refused at build: AggregateException |
| `compile.ArrayReverse` | builds clean; prints 3,2,1 / 1,2,3 | builds clean; prints 3,2,1 / 1,2,3 | builds clean; prints 3,2,1 / 1,2,3 |
| `compile.AsyncLinqPackage` | builds clean | builds clean | fails: error CS0121 |
| `compile.CertificateConstructor` | builds clean | builds clean | builds: warning SYSLIB0057 |
| `compile.FieldIdentifier` | builds clean | builds clean | builds: warning CS0169, warning CS9258 |
| `compile.ForwardedHeadersNetworks` | builds clean | builds clean | builds: warning ASPDEPR005 |
| `compile.LegacyWebHost` | builds clean | builds clean | builds: warning ASPDEPR008 |
| `compile.PasswordHashConstructor` | builds clean | builds clean | builds: warning SYSLIB0060 |
| `compile.TransitiveAdvisory` | builds clean | builds clean | builds: warning NU1903 |
| `compile.WithOpenApiCall` | builds clean | builds clean | builds: warning ASPDEPR002 |
| `configuration.null_in_json` | Name='', Retries=3, Hosts=['', ''] | Name='', Retries=3, Hosts=['', ''] | Name=null, Retries=null, Hosts=[null, null] |
| `di.getkeyedservice_with_anykey` | returned the AnyKey registration | returned the AnyKey registration | threw InvalidOperationException |
| `diagnostics.default_propagator_fields` | baggage, Correlation-Context, Request-Id, traceparent, tracestate | baggage, Correlation-Context, Request-Id, traceparent, tracestate | baggage, Correlation-Context, traceparent, tracestate |
| `hosting.backgroundservice_sync_work_blocks_startup` | yes: StartAsync waited for it | yes: StartAsync waited for it | no: StartAsync returned first |
| `http.factory_logs_header_values` | value written to the log | value written to the log | value redacted |
| `http.factory_primary_handler` | HttpClientHandler | HttpClientHandler | SocketsHttpHandler |
| `json.nullable_jsondocument_property` | null | null | a JsonDocument of kind Null |
| `json.property_named_like_the_type_discriminator` | serializes {"Type":"dog","Type":"Dog"} | serializes {"Type":"dog","Type":"Dog"} | throws InvalidOperationException |
| `language.array_contains_in_expression_tree` | binds to Enumerable.Contains, interprets | binds to Enumerable.Contains, interprets | binds to MemoryExtensions.Contains, interpreter throws ArgumentException |
| `net.mailaddress_consecutive_dots` | accepted first..last@example.org | accepted first..last@example.org | throws FormatException |
| `net.uri_longer_than_65519` | throws UriFormatException | throws UriFormatException | accepted, 70020 characters |
| `runtime.empty_environment_variable` | setting "" deletes the variable | setting "" deletes the variable | setting "" keeps an empty variable |
| `runtime.float_to_int_out_of_range` | (int)1e20=-2147483648, (int)NaN=-2147483648, (uint)-1.0=4294967295 | (int)1e20=-2147483648, (int)NaN=-2147483648, (uint)-1.0=4294967295 | (int)1e20=2147483647, (int)NaN=0, (uint)-1.0=0 |
| `runtime.server_gc_adaptation_mode` | server GC on, GCDynamicAdaptationMode 0 | server GC on, GCDynamicAdaptationMode 0 | server GC on, GCDynamicAdaptationMode 1 |
| `sdk.dotnet_new_sln_creates` | App.sln | App.slnx | App.slnx |
| `serialization.binaryformatter_with_the_opt_in` | serializes | serializes | throws PlatformNotSupportedException |
| `xml.obsolete_property_is_serialized` | no | no | yes |

Container base images, read from `/etc/os-release`: `aspnet:8.0` is Debian 12, `aspnet:10.0` is Ubuntu 24.04.

## What this does not show

- Linux x64 only. The floating-point conversion results are for that platform.
- No Entity Framework Core, no Blazor, no OpenAPI document generation, no trimming or Native AOT.
- No performance or memory measurement.
- `TransitiveAdvisory` depends on the public advisory database, which changes over time.
- Each probe is one small case. A change that does not show up here can still affect your code.
