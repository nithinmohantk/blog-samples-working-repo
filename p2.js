eval(localStorage.art_H); const G=window.G,p=G.p,h2=G.h2; const snip=window.snip;
const parts=[
h2('JSON decides whether Native AOT is possible'),
p(`A Native AOT executable contains only the code the compiler could see would be needed. A serialiser that discovers the properties of a type by reflection at run time gives the compiler nothing to see. System.Text.Json therefore has to be told at compile time which types cross the wire, through a source-generated context. The function has two: one for its own request and response bodies, one for the event Lambda delivers and the response it expects.`),
snip('csharp','handler','[JsonSourceGenerationOptions(','public sealed partial class EventJson : JsonSerializerContext;'),
p(`To see what happens without it, the project has a switch that swaps the generated serialiser for the reflection-based one. The compiler says so, with two warnings for each call:`),
snip('text','r_pub','/build/src/Quotes.Function/QuoteHandler.cs(97,55): warning IL3050','Use System.Text.Json source generation for native AOT applications.'),
p(`The build still succeeds. On the managed runtime that package answers normally. As Native AOT it starts, takes the event, and fails on the first request:`),
snip('text','r_aotlog','System.InvalidOperationException: Reflection-based serialization','   at Quotes.QuoteHandler.Handle(APIGatewayHttpApiV2ProxyRequest request, ILambdaContext context) + 0x6e'),
G.callout('warning','TREAT TRIM WARNINGS AS BUILD FAILURES',`<code>IL2026</code> and <code>IL3050</code> are the only notice you get before production. The package builds, deploys and passes a health check that does not touch the affected path. List both codes in <code>WarningsAsErrors</code> for the Native AOT build, and run every event shape through the built executable in the pipeline. The same applies to each NuGet package the function uses: an AWS SDK client, a logging sink or an ORM that relies on reflection will fail the same way.`),
h2('Building for Amazon Linux 2023'),
p(`The managed-runtime packages are portable assemblies and can be built anywhere. The Native AOT executable is linked against the C library of the machine that builds it, so it has to be built on the operating system it will run on. The sample does every build inside an Amazon Linux 2023 container, with the linker toolchain installed and an exact SDK version.`),
snip('bash','build','dnf install -y -q clang gcc zlib-devel','export DOTNET_ROOT=/opt/dotnet PATH=/opt/dotnet:$PATH'),
snip('bash','build','publish() { # name flavour reflection','> "/out/publish-$1.log" 2>&1 || { echo "publish $1 FAILED"; tail -n 20 "/out/publish-$1.log"; status=1; return; }'),
p(`The result of the five builds, with sizes in bytes:`),
snip('text','r_build','name            flavour','aot/bootstrap  7.2 MB'),
p(`The managed package is nine files and 0.2 MB zipped, because .NET itself is in the runtime. The Native AOT package is one 7.2 MB file, 3.4 MB zipped, with the parts of .NET it uses compiled in. It took 13 seconds to publish against 2 for the managed build. On a function this small the difference is noise; on a service with many dependencies the Native AOT link step becomes a visible part of the pipeline.`),
h2('Running the packages in the runtime emulator'),
p(`AWS publishes the images its runtimes are built from. Their entry point is the Lambda Runtime Interface Emulator, a small process that accepts an invocation over HTTP and passes it to the function through the same Runtime API that Lambda uses. Mounting a package into the image and posting an event to it tests the real runtime client, the real event serialisation and the real start-up path, with no account.`),
G.mer(G.MS+`
sequenceDiagram
    participant T as Test script
    participant E as Runtime emulator
    participant F as Function process
    T->>E: POST /2015-03-31/functions/function/invocations
    E->>F: Start the runtime (first request only)
    F->>E: GET next invocation
    E-->>F: The event
    F->>E: POST the response
    E-->>T: The response`),
p(`The plain image tags, <code>dotnet:10</code> and <code>provided:al2023</code>, move every time AWS patches them. A test that uses them changes without a commit. The sample asks the registry for the dated tags and takes the newest one on or before a chosen day, so a run can be repeated against the same runtime.`),
snip('python','pick','pattern = re.compile(','print(max(found)[2])'),
snip('text','r_ver','managed runtime image','image sizes            208 MB and 43 MB'),
p(`Each container is started with 512 MB of memory, and the package mounted read-only where Lambda would unpack it.`),
snip('python','emulate','def start(folder: str','    return began'),
p(`One detail of the images is worth knowing. For a zip deployment to <code>provided.al2023</code>, Lambda starts <code>/var/task/bootstrap</code>. The base image for that runtime looks for the file in <code>/var/runtime</code> instead, so that is where the test mounts it.`),
p(`The managed runtime turned out to have a second way in. Its start-up script, read out of the image, checks whether the handler setting names an assembly; if there is no such DLL but there is an executable file of that name, it runs the file directly:`),
snip('bash','r_boot','if [[ "${HANDLER_COL_INDEX}" == 0 ]]; then','    exit 104\n  fi'),
p(`So a Native AOT executable also runs on the <code>dotnet10</code> runtime with the handler set to <code>bootstrap</code>, which is the arrangement the AWS guidance on Native AOT describes. The test runs the Native AOT package both ways. All four configurations were sent the same six events:`),
snip('text','r_emu','ok    1-quote','ok    all four gave byte-identical bodies and the same status for every request')
];
G.save(2,parts)
