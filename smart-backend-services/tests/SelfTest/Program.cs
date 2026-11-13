// dotnet run -c Release -- <output dir>                                   against a small in-memory FHIR stand-in
// dotnet run -c Release -- <output dir> http://host/fhir [python script]  against a real FHIR R4 server behind the gateway
// dotnet run -c Release -- <output dir> stand-in python/verify_interop.py  the stand-in again, with the Python client
using System.Collections.Concurrent;
using System.Diagnostics;
using System.Net;
using System.Net.Http.Headers;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Http;
using Microsoft.Extensions.Logging;
using Smart.Backend;
using Smart.Backend.Server;

int passed = 0, failed = 0;
void Check(string name, bool condition, string detail = "")
{
    if (condition) { passed++; } else { failed++; }
    Console.WriteLine($"{(condition ? "ok  " : "FAIL")}  {name}{(condition || detail.Length == 0 ? "" : $"  [{detail}]")}");
}

string outDir = args[0];
Directory.CreateDirectory(outDir);
string? realFhir = args.Length > 1 && args[1] != "stand-in" ? args[1].TrimEnd('/') + "/" : null;
string? pythonScript = args.Length > 2 ? args[2] : null;
JsonSerializerOptions indented = new() { WriteIndented = true, Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping };
void Save(string name, JsonNode node) => File.WriteAllText(Path.Combine(outDir, name), node.ToJsonString(indented) + "\n");
string S(JsonNode? node) => node is JsonValue value && value.TryGetValue(out string? text) ? text : "";

Uri publicBase = new("http://127.0.0.1:5590/"), fhirBase = new(publicBase, "fhir/"), tokenUrl = new(publicBase, "oauth/token"), keysBase = new("http://127.0.0.1:5592/");
Uri upstream = new(realFhir ?? "http://127.0.0.1:5591/fhir/");
AdjustableClock clock = new();
ConcurrentQueue<AuditEvent> audit = new();

// ---- Keys. Generated for this run, held in memory, never written to the output directory. ----------------------
ECDsa reportingKey1 = ECDsa.Create(ECCurve.NamedCurves.nistP384), reportingKey2 = ECDsa.Create(ECCurve.NamedCurves.nistP384), strangerKey = ECDsa.Create(ECCurve.NamedCurves.nistP384);
ECDsa demographicsKey = ECDsa.Create(ECCurve.NamedCurves.nistP384), readOnlyKey = ECDsa.Create(ECCurve.NamedCurves.nistP384), seederKey = ECDsa.Create(ECCurve.NamedCurves.nistP384);
RSA loaderKey = RSA.Create(3072), pythonKey = RSA.Create(3072);
JsonObject KeySet(params AsymmetricAlgorithm[] keys) => new() { ["keys"] = new JsonArray([.. keys.Select(k => (JsonNode)Jose.PublicJwk(k))]) };

// ---- A place where one client publishes its keys, as the specification prefers. ---------------------------------
JsonObject publishedKeys = KeySet(reportingKey1);
ConcurrentQueue<string> seenAuthorization = new();
WebApplicationBuilder keysBuilder = WebApplication.CreateSlimBuilder();
keysBuilder.Logging.ClearProviders();
keysBuilder.WebHost.UseUrls(keysBase.GetLeftPart(UriPartial.Authority));
WebApplication keysHost = keysBuilder.Build();
keysHost.MapGet("/reporting-service/jwks.json", (HttpContext http) => { http.Response.Headers.CacheControl = "max-age=300"; return Results.Text(publishedKeys.ToJsonString(), "application/json"); });
keysHost.MapGet("/elsewhere/Practitioner/1", (HttpContext http) => { seenAuthorization.Enqueue(http.Request.Headers.Authorization.ToString()); return Results.Text("{\"resourceType\":\"Practitioner\"}", "application/fhir+json"); });
await keysHost.StartAsync();

WebApplication? stub = realFhir is null ? FhirStandIn.Build(upstream) : null;
if (stub is not null) { await stub.StartAsync(); }

Dictionary<string, ClientRegistration> registrations = new()
{
    ["reporting-service"] = new() { ClientId = "reporting-service", JwksUri = new Uri(keysBase, "reporting-service/jwks.json"), Scope = "system/Patient.rs system/Observation.rs" },
    ["demographics-sync"] = new() { ClientId = "demographics-sync", Jwks = KeySet(demographicsKey), Scope = "system/Patient.rs" },
    ["id-checker"] = new() { ClientId = "id-checker", Jwks = KeySet(readOnlyKey), Scope = "system/Patient.r" },
    ["lab-loader"] = new() { ClientId = "lab-loader", Jwks = KeySet(loaderKey), Scope = "system/Observation.cu system/Patient.r" },
    ["python-batch"] = new() { ClientId = "python-batch", Jwks = KeySet(pythonKey), Scope = "system/Patient.rs" },
    ["test-seeder"] = new() { ClientId = "test-seeder", Jwks = KeySet(seederKey), Scope = "system/*.cruds" },
};
SmartHostOptions hostOptions = new() { PublicBase = publicBase, UpstreamFhirBase = upstream, Clients = registrations, Audit = audit.Enqueue, Clock = clock };
WebApplication host = SmartHost.Build(hostOptions, out JwksResolver jwksResolver);
await host.StartAsync();

using HttpClient plain = new();
SmartBackendClient Client(string id, AsymmetricAlgorithm key, string scope, bool requireAll = true) =>
    new(plain, new SmartClientOptions { FhirBase = fhirBase, ClientId = id, Scope = scope, RequireAllScopes = requireAll }, new LocalKeySigner(key), clock);
HttpClient Http(SmartBackendClient client) => new(new SmartBackendHandler(client)) { BaseAddress = fhirBase };
async Task<(int Status, JsonObject Body, HttpResponseMessage Response)> Send(HttpClient http, HttpMethod method, string url, JsonNode? body = null, string? bearer = null)
{
    using HttpRequestMessage request = new(method, url);
    if (body is not null) { request.Content = new StringContent(body.ToJsonString(), Encoding.UTF8, "application/fhir+json"); }
    if (bearer is not null) { request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", bearer); }
    HttpResponseMessage response = await http.SendAsync(request);
    string text = await response.Content.ReadAsStringAsync();
    return ((int)response.StatusCode, text.Length > 0 && text.TrimStart().StartsWith('{') ? JsonNode.Parse(text)!.AsObject() : [], response);
}
string LastAudit(string area) => audit.Last(e => e.Area == area).Detail;

// A hand-built assertion, so each rule of the specification can be broken on purpose.
string Craft(string clientId, AsymmetricAlgorithm key, Action<JsonObject, JsonObject>? change = null, Func<byte[], byte[]>? sign = null)
{
    JsonObject header = new() { ["alg"] = Jose.AlgorithmFor(key), ["kid"] = S(Jose.PublicJwk(key)["kid"]), ["typ"] = "JWT" };
    JsonObject claims = new() { ["iss"] = clientId, ["sub"] = clientId, ["aud"] = tokenUrl.ToString(), ["exp"] = clock.GetUtcNow().AddMinutes(2).ToUnixTimeSeconds(), ["jti"] = Guid.NewGuid().ToString("N") };
    change?.Invoke(header, claims);
    string input = Jose.SigningInput(header, claims);
    byte[] bytes = Encoding.ASCII.GetBytes(input);
    return Jose.Compact(input, sign is null ? Jose.Sign(key, bytes) : sign(bytes));
}
async Task<(int Status, JsonObject Body, HttpResponseMessage Response)> Token(string assertion, string scope = "system/Patient.rs", Dictionary<string, string>? replace = null)
{
    Dictionary<string, string> form = new() { ["grant_type"] = "client_credentials", ["scope"] = scope, ["client_assertion_type"] = TokenService.AssertionType, ["client_assertion"] = assertion };
    foreach ((string key, string value) in replace ?? []) { if (value.Length == 0) { form.Remove(key); } else { form[key] = value; } }
    HttpResponseMessage response = await plain.PostAsync(tokenUrl, new FormUrlEncodedContent(form));
    return ((int)response.StatusCode, JsonNode.Parse(await response.Content.ReadAsStringAsync())!.AsObject(), response);
}

// ---- 1. Scopes -----------------------------------------------------------------------------------------------------
Console.WriteLine("== scopes");
ScopeSet registered = ScopeSet.Parse("system/Patient.rs system/Observation.rs")!;
(string Asked, string? Granted)[] grants =
[
    ("system/Patient.rs", "system/Patient.rs"), ("system/Patient.cruds", "system/Patient.rs"), ("system/Patient.r system/Patient.s", "system/Patient.rs"),
    ("system/Encounter.rs", ""), ("system/*.rs", ""), ("system/Observation.s system/Encounter.r", "system/Observation.s"),
    ("system/*.read", null), ("patient/Patient.rs", null), ("system/Patient.sr", null), ("system/Patient.", null), ("system/Observation.rs?category=laboratory", null), ("openid", null),
];
foreach ((string asked, string? granted) in grants)
{
    string? actual = ScopeSet.Parse(asked)?.GrantFrom(registered).ToString();
    Console.WriteLine($"  asked {asked,-44} -> {(actual is null ? "not a v2 system scope" : actual.Length == 0 ? "(nothing)" : actual)}");
    if (actual != granted) { Check($"grant for '{asked}'", false, $"expected '{granted}'"); }
}
Check("twelve requests against a registration of Patient.rs and Observation.rs give the expected grant or refusal", grants.All(g => ScopeSet.Parse(g.Asked)?.GrantFrom(registered).ToString() == g.Granted));
ScopeSet everything = ScopeSet.Parse("system/*.cruds")!;
Check("a wildcard registration grants a wildcard request, and a typed one within it", ScopeSet.Parse("system/*.rs")!.GrantFrom(everything).ToString() == "system/*.rs" && ScopeSet.Parse("system/Patient.cu")!.GrantFrom(everything).ToString() == "system/Patient.cu");
Check("write does not imply read, and read does not imply search", !ScopeSet.Parse("system/Observation.cu")!.Allows("Observation", 'r') && !ScopeSet.Parse("system/Patient.r")!.Allows("Patient", 's'));

// ---- 2. What a request needs ---------------------------------------------------------------------------------------
Console.WriteLine("== what a request needs");
JsonObject Transaction(params (string Method, string Url, string? IfNoneExist)[] entries) => new()
{
    ["resourceType"] = "Bundle", ["type"] = "transaction",
    ["entry"] = new JsonArray([.. entries.Select(e => (JsonNode)new JsonObject { ["request"] = e.IfNoneExist is null ? new JsonObject { ["method"] = e.Method, ["url"] = e.Url } : new JsonObject { ["method"] = e.Method, ["url"] = e.Url, ["ifNoneExist"] = e.IfNoneExist } })]),
};
(string Method, string Url, JsonObject? Body, string Expected)[] shapes =
[
    ("GET", "Patient/123", null, "system/Patient.r"),
    ("GET", "Patient/123/_history/2", null, "system/Patient.r"),
    ("GET", "Patient?family=Byrne", null, "system/Patient.s"),
    ("GET", "Patient/_history", null, "system/Patient.s"),
    ("GET", "Patient?_revinclude=Observation:subject", null, "system/Patient.s system/Observation.r"),
    ("GET", "Patient?_include=Patient:general-practitioner:Practitioner", null, "system/Patient.s system/Practitioner.r"),
    ("GET", "Patient?_include=Patient:general-practitioner", null, "refused"),
    ("GET", "Patient?_include:iterate=*", null, "system/Patient.s system/*.r"),
    ("GET", "Observation?subject:Patient.family=Byrne", null, "system/Observation.s system/Patient.s"),
    ("GET", "Observation?subject.family=Byrne", null, "refused"),
    ("GET", "Patient?_has:Observation:subject:code=1234-5", null, "system/Patient.s system/Observation.s"),
    ("GET", "Patient/123/Observation?code=1234-5", null, "system/Patient.r system/Observation.s"),
    ("GET", "Patient/123/$everything", null, "refused"),
    ("GET", "?_type=Patient,Observation", null, "system/*.s system/Patient.s system/Observation.s"),
    ("GET", "Patient?_filter=name eq x", null, "refused"),
    ("POST", "Patient/_search", null, "refused"),
    ("POST", "Observation", null, "system/Observation.c"),
    ("PUT", "Patient/123", null, "system/Patient.u"),
    ("PUT", "Patient?identifier=x|1", null, "system/Patient.u system/Patient.s"),
    ("PATCH", "Patient/123", null, "system/Patient.u"),
    ("DELETE", "Patient/123", null, "system/Patient.d"),
    ("DELETE", "Patient?identifier=x|1", null, "system/Patient.d system/Patient.s"),
    ("POST", "", Transaction(("POST", "Observation", null), ("PUT", "Patient/123", null), ("GET", "Encounter?subject=Patient/123", null)), "system/Observation.c system/Patient.u system/Encounter.s"),
    ("POST", "", Transaction(("POST", "Patient", "identifier=x|1")), "system/Patient.c system/Patient.s"),
    ("POST", "", Transaction(("POST", "Patient/$match", null)), "refused"),
    ("POST", "", new JsonObject { ["resourceType"] = "Patient" }, "refused"),
];
int shapeMismatches = 0;
foreach ((string method, string url, JsonObject? body, string expected) in shapes)
{
    string[] parts = url.Split('?', 2);
    Classification result = FhirRequestClassifier.Classify(method, parts[0], FhirRequestClassifier.ParseQuery(parts.Length > 1 ? parts[1] : ""), body);
    string actual = result.Refusal is null ? string.Join(' ', result.Needs) : "refused";
    string shown = body is null ? url : $"(base) Bundle of {string.Join(", ", body["entry"]?.AsArray().Select(e => $"{S(e!["request"]!["method"])} {S(e["request"]!["url"])}") ?? ["a Patient"])}";
    Console.WriteLine($"  {method,-6} {shown,-62} {(result.Refusal is null ? actual : $"refused: {result.Refusal}")}");
    if (actual != expected) { shapeMismatches++; Console.WriteLine($"         expected {expected}"); }
}
Check($"{shapes.Length} request shapes each need exactly the expected permissions, or are refused", shapeMismatches == 0, $"{shapeMismatches} mismatches");

// ---- 3. Discovery and a first token --------------------------------------------------------------------------------
Console.WriteLine("== discovery and a first token");
(int discoveryStatus, JsonObject configuration, HttpResponseMessage discoveryResponse) = await Send(plain, HttpMethod.Get, new Uri(fhirBase, ".well-known/smart-configuration").ToString());
Save("smart-configuration.json", configuration);
Check("discovery needs no token and is application/json", discoveryStatus == 200 && discoveryResponse.Content.Headers.ContentType?.MediaType == "application/json");
Check("it advertises client_credentials, private_key_jwt, RS384 and ES384, and the asymmetric client capability", S(configuration["token_endpoint"]) == tokenUrl.ToString()
    && configuration["grant_types_supported"]!.AsArray().Any(v => S(v) == "client_credentials") && configuration["token_endpoint_auth_methods_supported"]!.AsArray().Any(v => S(v) == "private_key_jwt")
    && configuration["token_endpoint_auth_signing_alg_values_supported"]!.AsArray().Select(S).SequenceEqual(["RS384", "ES384"]) && configuration["capabilities"]!.AsArray().Any(v => S(v) == "client-confidential-asymmetric"));
Check("the capability statement is public too", (await Send(plain, HttpMethod.Get, new Uri(fhirBase, "metadata").ToString())).Status == 200);

SmartBackendClient reporting = Client("reporting-service", reportingKey1, "system/Patient.rs system/Observation.rs");
string firstAssertion = await reporting.BuildAssertionAsync(tokenUrl);
ParsedJws shownAssertion = Jose.Parse(firstAssertion)!;
Save("assertion-decoded.json", new JsonObject { ["header"] = shownAssertion.Header.DeepClone(), ["claims"] = shownAssertion.Payload.DeepClone(), ["signature"] = $"({shownAssertion.Signature.Length} bytes, not shown)" });
(int tokenStatus, JsonObject tokenBody, HttpResponseMessage tokenResponse) = await Token(firstAssertion, "system/Patient.rs system/Observation.rs");
ParsedJws accessToken = Jose.Parse(S(tokenBody["access_token"]))!;
JsonObject shownResponse = (JsonObject)tokenBody.DeepClone();
shownResponse["access_token"] = "(a signed JWT, not shown)";
Save("token-response.json", shownResponse);
Save("access-token-decoded.json", new JsonObject { ["header"] = accessToken.Header.DeepClone(), ["claims"] = accessToken.Payload.DeepClone() });
Check("an ES384 assertion from a client with a JWK Set URL gets a bearer token for 300 seconds", tokenStatus == 200 && S(tokenBody["token_type"]) == "bearer" && tokenBody["expires_in"]!.GetValue<int>() == 300 && S(tokenBody["scope"]) == "system/Observation.rs system/Patient.rs", tokenBody.ToJsonString());
Check("the token response may not be cached and carries no refresh token", tokenResponse.Headers.CacheControl?.NoStore == true && tokenBody["refresh_token"] is null);
Check("the access token names the client, the scope and one FHIR server, and expires five minutes after issue", accessToken.ClaimString("client_id") == "reporting-service" && accessToken.Audiences.SequenceEqual([fhirBase.ToString()])
    && accessToken.ClaimNumber("exp") - accessToken.ClaimNumber("iat") == 300 && accessToken.ClaimString("scope") == "system/Observation.rs system/Patient.rs");
SmartBackendClient loader = Client("lab-loader", loaderKey, "system/Observation.cu system/Patient.r");
Check("an RS384 assertion from a client with a registered JWK Set is accepted as well", (await loader.GetTokenAsync()).Scope == "system/Observation.cu system/Patient.r");

// ---- 4. Everything the token endpoint must refuse ------------------------------------------------------------------
Console.WriteLine("== what the token endpoint refuses");
int fetchesBefore = jwksResolver.Fetches;
string replayed = Craft("demographics-sync", demographicsKey);
byte[] publicKeyAsSecret = Encoding.UTF8.GetBytes(Jose.PublicJwk(demographicsKey).ToJsonString());
(string Name, Func<Task<(int Status, JsonObject Body, HttpResponseMessage Response)>> Attempt, string Error, string Reason)[] refusals =
[
    ("an assertion signed with a key that is not the registered one", () => Token(Craft("demographics-sync", demographicsKey, null, bytes => Jose.Sign(strangerKey, bytes))), "invalid_client", "signature does not verify"),
    ("alg none with an empty signature", () => Token(Craft("demographics-sync", demographicsKey, (h, _) => h["alg"] = "none", _ => [])), "invalid_client", "alg 'none'"),
    ("alg HS384, signed with the public key as if it were a shared secret", () => Token(Craft("demographics-sync", demographicsKey, (h, _) => h["alg"] = "HS384", bytes => HMACSHA384.HashData(publicKeyAsSecret, bytes))), "invalid_client", "alg 'HS384'"),
    ("alg RS384 in the header of an assertion signed with an EC key", () => Token(Craft("demographics-sync", demographicsKey, (h, _) => h["alg"] = "RS384")), "invalid_client", "no single RS384 key"),
    ("a key ID that is not in the registered key set", () => Token(Craft("demographics-sync", demographicsKey, (h, _) => h["kid"] = "some-other-key")), "invalid_client", "no single ES384 key"),
    ("no typ in the header", () => Token(Craft("demographics-sync", demographicsKey, (h, _) => h.Remove("typ"))), "invalid_client", "typ is not JWT"),
    ("a jku header pointing at a key set the caller controls", () => Token(Craft("demographics-sync", strangerKey, (h, _) => h["jku"] = new Uri(keysBase, "attacker/jwks.json").ToString())), "invalid_client", "jku is not the registered"),
    ("a client that was never registered", () => Token(Craft("unknown-service", strangerKey)), "invalid_client", "unknown client"),
    ("iss and sub that differ", () => Token(Craft("demographics-sync", demographicsKey, (_, c) => c["sub"] = "reporting-service")), "invalid_client", "iss and sub differ"),
    ("an audience that is the FHIR base, not the token endpoint", () => Token(Craft("demographics-sync", demographicsKey, (_, c) => c["aud"] = fhirBase.ToString())), "invalid_client", "aud is not this token endpoint"),
    ("an assertion that expired a minute ago", () => Token(Craft("demographics-sync", demographicsKey, (_, c) => c["exp"] = clock.GetUtcNow().AddMinutes(-1).ToUnixTimeSeconds())), "invalid_client", "has expired"),
    ("an assertion valid for ten minutes", () => Token(Craft("demographics-sync", demographicsKey, (_, c) => c["exp"] = clock.GetUtcNow().AddMinutes(10).ToUnixTimeSeconds())), "invalid_client", "more than five minutes"),
    ("an assertion with no exp", () => Token(Craft("demographics-sync", demographicsKey, (_, c) => c.Remove("exp"))), "invalid_client", "no exp"),
    ("an assertion with no jti", () => Token(Craft("demographics-sync", demographicsKey, (_, c) => c.Remove("jti"))), "invalid_client", "no usable jti"),
    ("the same assertion presented a second time", async () => { await Token(replayed); return await Token(replayed); }, "invalid_client", "used before"),
    ("a payload changed after signing", () => { string[] p = Craft("demographics-sync", demographicsKey).Split('.'); return Token($"{p[0]}.{System.Buffers.Text.Base64Url.EncodeToString(Encoding.UTF8.GetBytes(Jose.Parse(string.Join('.', p))!.Payload.ToJsonString().Replace("\"jti\":\"", "\"jti\":\"x")))}.{p[2]}"); }, "invalid_client", "signature does not verify"),
    ("text that is not a JWT", () => Token("not.a.jwt"), "invalid_client", "not a compact JWS"),
    ("grant_type authorization_code", () => Token(Craft("demographics-sync", demographicsKey), replace: new() { ["grant_type"] = "authorization_code" }), "unsupported_grant_type", "grant_type"),
    ("no client assertion", () => Token("", replace: new() { ["client_assertion"] = "" }), "invalid_request", "missing"),
    ("a v1 scope, system/*.read", () => Token(Craft("demographics-sync", demographicsKey), "system/*.read"), "invalid_scope", "not a list of SMART v2 system scopes"),
    ("a patient-level scope", () => Token(Craft("demographics-sync", demographicsKey), "patient/Patient.rs"), "invalid_scope", "not a list of SMART v2 system scopes"),
    ("a scope outside the registration", () => Token(Craft("demographics-sync", demographicsKey), "system/Observation.rs"), "invalid_scope", "nothing in"),
];
int refusalMismatches = 0, leaks = 0;
foreach ((string name, var attempt, string error, string reason) in refusals)
{
    (int status, JsonObject body, _) = await attempt();
    string logged = LastAudit("token");
    bool ok = status == (error == "invalid_client" ? 401 : 400) && S(body["error"]) == error && reason.Split('|').Any(logged.Contains);
    if (error == "invalid_client" && body["error_description"] is not null) { leaks++; }
    if (!ok) { refusalMismatches++; }
    Console.WriteLine($"  {(ok ? "refused" : "WRONG  ")} {status} {S(body["error"]),-22} {name}");
    Console.WriteLine($"             audit: {logged}");
}
Check($"{refusals.Length} bad token requests are each refused with the right error, and the audit log has the reason", refusalMismatches == 0, $"{refusalMismatches} mismatches");
Check("no invalid_client response tells the caller which check failed", leaks == 0);
Check("none of them made the server fetch a key set from a URL the caller chose", jwksResolver.Fetches == fetchesBefore, $"{fetchesBefore} -> {jwksResolver.Fetches}");
(int narrowStatus, JsonObject narrowBody, _) = await Token(Craft("demographics-sync", demographicsKey), "system/Patient.cruds");
Check("asking for more than the registration allows yields a token for the part that is allowed", narrowStatus == 200 && S(narrowBody["scope"]) == "system/Patient.rs", narrowBody.ToJsonString());
SmartTokenException? narrowed = null;
try { await Client("demographics-sync", demographicsKey, "system/Patient.cruds").GetTokenAsync(); }
catch (SmartTokenException error) { narrowed = error; }
Check("the client treats a narrower grant as an error by default, and accepts it when told to", narrowed?.Error == "insufficient_scope" && (await Client("demographics-sync", demographicsKey, "system/Patient.cruds", requireAll: false).GetTokenAsync()).Scope == "system/Patient.rs");
using (HttpRequestMessage twice = new(HttpMethod.Post, tokenUrl) { Content = new StringContent($"grant_type=client_credentials&grant_type=client_credentials&scope=system%2FPatient.rs&client_assertion_type={Uri.EscapeDataString(TokenService.AssertionType)}&client_assertion=x", Encoding.ASCII, "application/x-www-form-urlencoded") })
{
    HttpResponseMessage repeated = await plain.SendAsync(twice);
    Check("a repeated parameter is an invalid request", (int)repeated.StatusCode == 400 && (await repeated.Content.ReadAsStringAsync()).Contains("invalid_request"));
}

// ---- 5. Key rotation through the JWK Set URL -----------------------------------------------------------------------
Console.WriteLine("== key rotation");
int fetches = jwksResolver.Fetches;
Check("a second token for the same client does not fetch its key set again", (await Token(Craft("reporting-service", reportingKey1))).Status == 200 && jwksResolver.Fetches == fetches);
publishedKeys = KeySet(reportingKey1, reportingKey2);
(int tooSoon, _, _) = await Token(Craft("reporting-service", reportingKey2));
for (int i = 0; i < 5; i++) { await Token(Craft("reporting-service", strangerKey)); }
Check("an unknown key ID within ten seconds of the last fetch is refused without another fetch, however often it is tried", tooSoon == 401 && jwksResolver.Fetches == fetches, $"{tooSoon}, fetches {fetches} -> {jwksResolver.Fetches}");
clock.Advance(TimeSpan.FromSeconds(11));
Check("after that, an unknown key ID triggers one fetch and the new key is accepted", (await Token(Craft("reporting-service", reportingKey2))).Status == 200 && jwksResolver.Fetches == fetches + 1, $"fetches {jwksResolver.Fetches - fetches}");
publishedKeys = KeySet(reportingKey2);
Check("a key removed from the published set is still accepted while the cached set is fresh", (await Token(Craft("reporting-service", reportingKey1))).Status == 200);
clock.Advance(TimeSpan.FromSeconds(301));
Check("once the cache lifetime the client asked for has passed, the removed key is refused", (await Token(Craft("reporting-service", reportingKey1))).Status == 401 && (await Token(Craft("reporting-service", reportingKey2))).Status == 200);
reporting = Client("reporting-service", reportingKey2, "system/Patient.rs system/Observation.rs");

// ---- 6. The gateway in front of the FHIR server --------------------------------------------------------------------
Console.WriteLine($"== the gateway, in front of {(realFhir is null ? "the in-memory stand-in" : "a FHIR server")}");
HttpClient seeder = Http(Client("test-seeder", seederKey, "system/*.cruds")), reports = Http(reporting);
HttpClient demographics = Http(Client("demographics-sync", demographicsKey, "system/Patient.rs")), idChecker = Http(Client("id-checker", readOnlyKey, "system/Patient.r")), labLoader = Http(loader);
JsonObject Patient(string family) => new() { ["resourceType"] = "Patient", ["identifier"] = new JsonArray(new JsonObject { ["system"] = "urn:oid:2.999.1.1", ["value"] = $"SMART-{family}" }), ["name"] = new JsonArray(new JsonObject { ["family"] = family }) };
JsonObject Observation(string patientId, int value) => new()
{
    ["resourceType"] = "Observation", ["status"] = "final",
    ["code"] = new JsonObject { ["coding"] = new JsonArray(new JsonObject { ["system"] = "http://loinc.org", ["code"] = "8867-4", ["display"] = "Heart rate" }) },
    ["subject"] = new JsonObject { ["reference"] = $"Patient/{patientId}" },
    ["valueQuantity"] = new JsonObject { ["value"] = value, ["unit"] = "beats/minute", ["system"] = "http://unitsofmeasure.org", ["code"] = "/min" },
};
(int created, JsonObject createdPatient, HttpResponseMessage createResponse) = await Send(seeder, HttpMethod.Post, "Patient", Patient("Byrne"));
string patientId = S(createdPatient["id"]);
string[] observationIds = new string[3];
for (int i = 0; i < 3; i++) { observationIds[i] = S((await Send(seeder, HttpMethod.Post, "Observation", Observation(patientId, 60 + i))).Body["id"]); }
Check("a client with system/*.cruds creates a patient and three observations through the gateway", created == 201 && patientId.Length > 0 && observationIds.All(id => id.Length > 0), $"{created}");
Check("the Location header names the public address, not the server behind the gateway", createResponse.Headers.Location?.ToString().StartsWith(fhirBase.ToString(), StringComparison.Ordinal) == true, createResponse.Headers.Location?.ToString() ?? "none");

(int noToken, _, HttpResponseMessage noTokenResponse) = await Send(plain, HttpMethod.Get, new Uri(fhirBase, $"Patient/{patientId}").ToString());
Check("no token: 401 with a Bearer challenge", noToken == 401 && noTokenResponse.Headers.WwwAuthenticate.ToString() == "Bearer");
string good = (await reporting.GetTokenAsync()).Value;
string[] goodParts = good.Split('.');
string forged = $"{goodParts[0]}.{System.Buffers.Text.Base64Url.EncodeToString(Encoding.UTF8.GetBytes(Jose.Parse(good)!.Payload.ToJsonString().Replace("system/Observation.rs system/Patient.rs", "system/*.cruds")))}.{goodParts[2]}";
(int forgedStatus, _, HttpResponseMessage forgedResponse) = await Send(plain, HttpMethod.Get, new Uri(fhirBase, $"Patient/{patientId}").ToString(), bearer: forged);
Check("a token whose scope was edited after signing: 401 invalid_token", forgedStatus == 401 && forgedResponse.Headers.WwwAuthenticate.ToString().Contains("invalid_token"));
Check("a client assertion presented as an access token: 401", (await Send(plain, HttpMethod.Get, new Uri(fhirBase, $"Patient/{patientId}").ToString(), bearer: Craft("reporting-service", reportingKey2))).Status == 401);

(int readStatus, JsonObject readBody, _) = await Send(reports, HttpMethod.Get, $"Patient/{patientId}");
(int searchStatus, JsonObject searchBody, _) = await Send(reports, HttpMethod.Get, $"Patient?identifier={Uri.EscapeDataString("urn:oid:2.999.1.1|SMART-Byrne")}");
Check("Patient.rs: read and search both succeed", readStatus == 200 && S(readBody["name"]![0]!["family"]) == "Byrne" && searchStatus == 200 && searchBody["entry"]!.AsArray().Count == 1);
(int revStatus, JsonObject revBody, _) = await Send(reports, HttpMethod.Get, $"Patient?_id={patientId}&_revinclude=Observation:subject");
int Included(JsonObject bundle) => bundle["entry"]?.AsArray().Count(e => S(e!["resource"]!["resourceType"]) == "Observation") ?? 0;
Check("Patient.rs and Observation.rs: a search that pulls in the patient's observations returns all three", revStatus == 200 && Included(revBody) == 3, $"{revStatus}, {Included(revBody)}");

(int narrowRead, _, _) = await Send(demographics, HttpMethod.Get, $"Patient/{patientId}");
(int otherType, JsonObject otherBody, HttpResponseMessage otherResponse) = await Send(demographics, HttpMethod.Get, $"Observation?subject=Patient/{patientId}");
Check("Patient.rs only: reading a patient succeeds; searching observations is 403 and names the missing scope", narrowRead == 200 && otherType == 403 && S(otherBody["resourceType"]) == "OperationOutcome"
    && otherResponse.Headers.WwwAuthenticate.ToString().Contains("insufficient_scope") && otherResponse.Headers.WwwAuthenticate.ToString().Contains("system/Observation.s"), otherResponse.Headers.WwwAuthenticate.ToString());
(int sideDoor, _, _) = await Send(demographics, HttpMethod.Get, $"Patient?_id={patientId}&_revinclude=Observation:subject");
using HttpClient direct = new();
JsonObject leaked = JsonNode.Parse(await direct.GetStringAsync(new Uri(upstream, $"Patient?_id={patientId}&_revinclude=Observation:subject")))!.AsObject();
Console.WriteLine($"  asked of the FHIR server directly, the same search returns {Included(leaked)} Observation resources");
Check("Patient.rs only: the same patient search with _revinclude=Observation:subject is 403, though the FHIR server alone would answer it", sideDoor == 403 && Included(leaked) == 3, $"{sideDoor}, {Included(leaked)}");
Check("Patient.rs only: a chained search and a _has search that ask about observations are 403", (await Send(demographics, HttpMethod.Get, "Patient?_has:Observation:subject:code=8867-4")).Status == 403
    && (await Send(reports, HttpMethod.Get, "Observation?subject:Patient.family=Byrne")).Status == 200 && (await Send(reports, HttpMethod.Get, "Observation?subject.family=Byrne")).Status == 403);
Check("Patient.rs only: create, update and delete are 403", (await Send(demographics, HttpMethod.Post, "Patient", Patient("Nolan"))).Status == 403 && (await Send(demographics, HttpMethod.Put, $"Patient/{patientId}", readBody)).Status == 403
    && (await Send(demographics, HttpMethod.Delete, $"Patient/{patientId}")).Status == 403);
Check("Patient.r only: read succeeds and search is 403", (await Send(idChecker, HttpMethod.Get, $"Patient/{patientId}")).Status == 200 && (await Send(idChecker, HttpMethod.Get, "Patient?family=Byrne")).Status == 403);
Check("an operation and a search by POST are refused whatever the scope", (await Send(seeder, HttpMethod.Get, $"Patient/{patientId}/$everything")).Status == 403 && (await Send(seeder, HttpMethod.Post, "Patient/_search")).Status == 403);

(int loaded, JsonObject loadedBody, _) = await Send(labLoader, HttpMethod.Post, "Observation", Observation(patientId, 72));
Check("Observation.cu: create succeeds, and reading back what was just written is 403", loaded == 201 && (await Send(labLoader, HttpMethod.Get, $"Observation/{S(loadedBody["id"])}")).Status == 403, $"{loaded}");
JsonObject Batch(params (string Method, string Url, JsonObject Resource)[] entries) => new()
{
    ["resourceType"] = "Bundle", ["type"] = "transaction",
    ["entry"] = new JsonArray([.. entries.Select(e => (JsonNode)new JsonObject { ["resource"] = e.Resource, ["request"] = new JsonObject { ["method"] = e.Method, ["url"] = e.Url } })]),
};
JsonObject renamed = (JsonObject)readBody.DeepClone();
renamed.Remove("meta");
(int mixed, JsonObject mixedBody, _) = await Send(labLoader, HttpMethod.Post, "", Batch(("POST", "Observation", Observation(patientId, 80)), ("PUT", $"Patient/{patientId}", renamed)));
(int clean, _, _) = await Send(labLoader, HttpMethod.Post, "", Batch(("POST", "Observation", Observation(patientId, 81)), ("POST", "Observation", Observation(patientId, 82))));
Check("Observation.cu: a transaction of two observations succeeds; one that also updates a patient is 403 as a whole", clean == 200 && mixed == 403 && S(mixedBody["issue"]![0]!["diagnostics"]).Contains("system/Patient.u"), $"{clean} {mixed}");
int observationsNow = (await Send(seeder, HttpMethod.Get, $"Observation?subject=Patient/{patientId}&_summary=count")).Body["total"]!.GetValue<int>();
Check("nothing from the refused transaction was written: six observations exist", observationsNow == 6, $"{observationsNow}");

(int pageStatus, JsonObject page, _) = await Send(reports, HttpMethod.Get, $"Observation?subject=Patient/{patientId}&_count=2");
string next = S(page["link"]?.AsArray().FirstOrDefault(l => S(l!["relation"]) == "next")?["url"]);
Check("a paged search returns a next link at the public address, with a page token", pageStatus == 200 && next.StartsWith(fhirBase.ToString().TrimEnd('/'), StringComparison.Ordinal) && next.Contains("_pt=") && !page.ToJsonString().Contains(upstream.Authority), next.Length > 80 ? next[..80] : next);
(int nextStatus, JsonObject nextPage, _) = await Send(reports, HttpMethod.Get, next);
Check("the client that ran the search can follow it", nextStatus == 200 && nextPage["entry"]!.AsArray().Count > 0, $"{nextStatus}");
Check("another client, with every scope, cannot follow that link, and nobody can follow it without the page token", (await Send(seeder, HttpMethod.Get, next)).Status == 403 && (await Send(reports, HttpMethod.Get, next[..next.IndexOf("&_pt=", StringComparison.Ordinal)])).Status == 403);

await Send(reports, HttpMethod.Get, new Uri(keysBase, "elsewhere/Practitioner/1").ToString());
Check("a request to another host through the same HttpClient carries no token", seenAuthorization.Count == 1 && seenAuthorization.All(value => value.Length == 0), string.Join("|", seenAuthorization));

// ---- 7. The client under load, at expiry and after a server restart ------------------------------------------------
Console.WriteLine("== the client over time");
SmartBackendClient busy = Client("demographics-sync", demographicsKey, "system/Patient.rs");
HttpClient busyHttp = Http(busy);
int[] statuses = await Task.WhenAll(Enumerable.Range(0, 20).Select(async _ => (await Send(busyHttp, HttpMethod.Get, $"Patient/{patientId}")).Status));
Check("twenty concurrent requests on a cold client result in one token request", statuses.All(s => s == 200) && busy.TokenRequests == 1, $"{busy.TokenRequests}");
string aging = (await busy.GetTokenAsync()).Value;
clock.Advance(TimeSpan.FromSeconds(271));
Check("thirty seconds before expiry the client replaces the token without being asked", (await Send(busyHttp, HttpMethod.Get, $"Patient/{patientId}")).Status == 200 && busy.TokenRequests == 2, $"{busy.TokenRequests}");
clock.Advance(TimeSpan.FromSeconds(30));
Check("the old token, presented after its five minutes, is 401", (await Send(plain, HttpMethod.Get, new Uri(fhirBase, $"Patient/{patientId}").ToString(), bearer: aging)).Status == 401);
await host.StopAsync();
await host.DisposeAsync();
host = SmartHost.Build(hostOptions, out jwksResolver);
await host.StartAsync();
int before = busy.TokenRequests;
(int afterRestart, _, _) = await Send(busyHttp, HttpMethod.Get, $"Patient/{patientId}");
Check("after the server restarts with a new signing key, the cached token gets 401 and the handler recovers with one new token", afterRestart == 200 && busy.TokenRequests == before + 1, $"{afterRestart}, {busy.TokenRequests - before}");

// ---- 8. Another implementation, in another language ----------------------------------------------------------------
if (pythonScript is not null)
{
    Console.WriteLine("== a Python client with PyJWT against the same endpoints");
    clock.Reset();      // the Python process reads the real clock, so the server must as well
    string keyDirectory = Directory.CreateTempSubdirectory("smart-key-").FullName, keyFile = Path.Combine(keyDirectory, "python-batch.pem");
    File.WriteAllText(keyFile, pythonKey.ExportPkcs8PrivateKeyPem());      // a throwaway key, outside the output directory, deleted below
    try
    {
        ProcessStartInfo start = new("python", [pythonScript, fhirBase.ToString(), "python-batch", keyFile, S(Jose.PublicJwk(pythonKey)["kid"]), new Uri(publicBase, "oauth/jwks").ToString()]) { RedirectStandardOutput = true, RedirectStandardError = true };
        using Process python = Process.Start(start)!;
        string output = await python.StandardOutput.ReadToEndAsync(), errors = await python.StandardError.ReadToEndAsync();
        await python.WaitForExitAsync();
        Console.WriteLine("  " + output.TrimEnd().Replace("\n", "\n  "));
        Check("the Python client's checks all pass", python.ExitCode == 0, errors.Length > 300 ? errors[^300..] : errors);
    }
    finally { Directory.Delete(keyDirectory, recursive: true); }
}

// ---- 9. The audit trail --------------------------------------------------------------------------------------------
Console.WriteLine("== the audit trail");
AuditEvent[] events = [.. audit];
File.WriteAllLines(Path.Combine(outDir, "audit.jsonl"), events.Select(e => JsonSerializer.Serialize(e)));
foreach (AuditEvent e in events.Where(e => e.Area == "fhir" && e.ClientId == "demographics-sync").Take(6)) { Console.WriteLine($"  {e.ClientId,-18} {e.Decision,-8} {e.Detail}"); }
string everything_ = string.Join('\n', events.Select(e => e.Detail));
Check($"{events.Length} audit events were written, and none contains a token, an assertion or a search value", events.Length > 100 && !everything_.Contains("eyJ") && !everything_.Contains("SMART-Byrne") && !everything_.Contains("8867-4"));
Check("every refusal at the gateway is in the audit trail with the client and the reason", events.Count(e => e.Area == "fhir" && e.Decision == "403" && e.ClientId != "?" && e.Detail.Contains(": ")) >= 12 && events.Any(e => e.Decision == "401"), $"{events.Count(e => e.Area == "fhir" && e.Decision == "403")}");

await host.StopAsync();
await keysHost.StopAsync();
if (stub is not null) { await stub.StopAsync(); }
Console.WriteLine($"\n{passed} of {passed + failed} checks passed");
return failed == 0 ? 0 : 1;

/// <summary>A clock that can be moved forward, shared by the server and the clients so a test need not wait five minutes.</summary>
internal sealed class AdjustableClock : TimeProvider
{
    private TimeSpan _ahead = TimeSpan.Zero;
    public void Advance(TimeSpan by) => _ahead += by;
    public void Reset() => _ahead = TimeSpan.Zero;
    public override DateTimeOffset GetUtcNow() => DateTimeOffset.UtcNow + _ahead;
}

/// <summary>Just enough of a FHIR server to exercise the gateway without Docker. The real run uses HAPI FHIR.</summary>
internal static class FhirStandIn
{
    public static WebApplication Build(Uri fhirBase)
    {
        ConcurrentDictionary<string, JsonObject> store = new();
        ConcurrentDictionary<string, List<JsonObject>> pages = new();
        int nextId = 0;
        string root = fhirBase.ToString().TrimEnd('/');
        WebApplicationBuilder builder = WebApplication.CreateSlimBuilder();
        builder.Logging.ClearProviders();
        builder.WebHost.UseUrls(fhirBase.GetLeftPart(UriPartial.Authority));
        WebApplication app = builder.Build();
        IResult Json(JsonNode node, int status = 200) => Results.Text(node.ToJsonString(), "application/fhir+json", statusCode: status);
        JsonObject Bundle(IEnumerable<JsonObject> resources, string type = "searchset") => new()
        {
            ["resourceType"] = "Bundle", ["type"] = type,
            ["entry"] = new JsonArray([.. resources.Select(r => (JsonNode)new JsonObject { ["fullUrl"] = $"{root}/{r["resourceType"]}/{r["id"]}", ["resource"] = r.DeepClone() })]),
        };
        JsonObject Store(JsonObject resource)
        {
            resource["id"] = Interlocked.Increment(ref nextId).ToString(System.Globalization.CultureInfo.InvariantCulture);
            store[$"{resource["resourceType"]}/{resource["id"]}"] = resource;
            return resource;
        }
        app.MapGet("/fhir/metadata", () => Json(new JsonObject { ["resourceType"] = "CapabilityStatement", ["status"] = "active" }));
        app.MapGet("/fhir", (HttpRequest request) => pages.TryRemove(request.Query["_getpages"].ToString(), out List<JsonObject>? rest) ? Json(Bundle(rest)) : Results.StatusCode(410));
        app.MapPost("/fhir", async (HttpRequest request) =>
        {
            JsonObject bundle = (await JsonNode.ParseAsync(request.Body))!.AsObject();
            foreach (JsonNode? entry in bundle["entry"]!.AsArray()) { if (entry!["request"]!["method"]!.GetValue<string>() == "POST") { Store(entry["resource"]!.DeepClone().AsObject()); } }
            return Json(new JsonObject { ["resourceType"] = "Bundle", ["type"] = "transaction-response" });
        });
        app.MapPost("/fhir/{type}", async (string type, HttpRequest request, HttpResponse response) =>
        {
            JsonObject resource = Store((await JsonNode.ParseAsync(request.Body))!.AsObject());
            response.Headers.Location = $"{root}/{type}/{resource["id"]}/_history/1";
            return Json(resource, 201);
        });
        app.MapGet("/fhir/{type}/{id}", (string type, string id) => store.TryGetValue($"{type}/{id}", out JsonObject? found) ? Json(found) : Results.NotFound());
        app.MapGet("/fhir/{type}", (string type, HttpRequest request) =>
        {
            List<JsonObject> found = [.. store.Values.Where(r => r["resourceType"]!.GetValue<string>() == type).OrderBy(r => int.Parse(r["id"]!.GetValue<string>(), System.Globalization.CultureInfo.InvariantCulture))];
            if (request.Query["_id"].ToString() is { Length: > 0 } wanted) { found = [.. found.Where(r => r["id"]!.GetValue<string>() == wanted)]; }
            if (request.Query["identifier"].ToString() is { Length: > 0 } identifier) { found = [.. found.Where(r => r["identifier"]?[0]?["value"]?.GetValue<string>() == identifier.Split('|')[^1])]; }
            if (request.Query["_summary"] == "count") { return Json(new JsonObject { ["resourceType"] = "Bundle", ["type"] = "searchset", ["total"] = found.Count }); }
            // Like a real server, the stand-in hands back whatever _revinclude asks for. Stopping that is the gateway's job.
            List<JsonObject> included = request.Query["_revinclude"] == "Observation:subject" ? [.. store.Values.Where(r => r["resourceType"]!.GetValue<string>() == "Observation")] : [];
            int count = int.TryParse(request.Query["_count"], out int asked) ? asked : 50;
            JsonObject bundle = Bundle([.. found.Take(count), .. included]);
            if (found.Count > count)
            {
                string pageId = Guid.NewGuid().ToString();
                pages[pageId] = [.. found.Skip(count)];
                bundle["link"] = new JsonArray(new JsonObject { ["relation"] = "next", ["url"] = $"{root}?_getpages={pageId}&_getpagesoffset={count}&_count={count}&_bundletype=searchset" });
            }
            return Json(bundle);
        });
        return app;
    }
}
