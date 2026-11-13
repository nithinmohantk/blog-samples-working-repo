eval(localStorage.art_H); const G=window.G,p=G.p,h2=G.h2; const I=k=>JSON.parse(localStorage['ev_img'+k]);
window.IM=(k,cap)=>G.img('ZZ'+k,I(k).alt,cap).split('ZZ'+k+'_ID').join(String(I(k).id)).split('ZZ'+k+'_URL').join(I(k).url);
window.SN=(k,a,b)=>{const t=localStorage['ev_code_'+k];const i=t.indexOf(a);const j=t.indexOf(b,i);if(i<0||j<0)throw new Error('marker '+k+' '+(i<0?a:b).slice(0,40));return t.slice(i,j+b.length)};
window.SNIPS=[]; window.snip=(lang,k,a,b)=>{const t=window.SN(k,a,b);window.SNIPS.push([k,t]);return G.code(lang,t)}; const snip=window.snip;
const parts=[
p(`The .NET 10 managed runtime has been available on AWS Lambda since January. With it, a .NET team has three ways to ship the same function: as ordinary assemblies that the runtime compiles as they run, as the same assemblies with SnapStart restoring a snapshot instead of starting cold, or as a Native AOT executable with no just-in-time compiler in it at all. Each one moves the cold start, and each one moves something else with it: who patches .NET, which libraries still work, and what appears on the bill.`),
p(`<a href="https://www.dataa.dev/2026/04/04/ecs-express-mode-app-runner-or-lambda-for-a-small-api/">Last week's cost model</a> put Lambda first for a small API that sits idle for much of the day. This article takes the next question for a .NET team that makes that choice. It builds one function three ways from one source tree, runs every build in the AWS Lambda base images under the Runtime Interface Emulator, and reads the SnapStart rules against the code that has to obey them.`),
G.callout('info','SCOPE',`.NET 10 with SDK 10.0.201, x86_64, zip-style packages for the <code>dotnet10</code> and <code>provided.al2023</code> runtimes. Everything was built and run in containers; no function was created in an AWS account. The emulator shows whether a package starts, whether it answers correctly and how the builds compare with each other. It cannot show a Lambda cold start, and it cannot take a SnapStart snapshot.`),
h2('What the .NET 10 runtime brings'),
p(`AWS released the <code>dotnet10</code> managed runtime and the matching container base image on 8 January 2026. Like the .NET 8 runtime it is built on Amazon Linux 2023. .NET 10 is a long-term support release, which Microsoft supports until November 2028, so for most teams this is the runtime to move .NET 8 functions to. The upgrade itself is covered in <a href="https://www.dataa.dev/2026/02/07/moving-a-dotnet-8-api-to-dotnet-10-what-breaks-between-two-lts-releases/">Moving a .NET 8 API to .NET 10</a>.`),
G.table(['Item','At the .NET 10 launch'],[
['Managed runtime identifier','<code>dotnet10</code>'],
['Container base image','<code>public.ecr.aws/lambda/dotnet:10</code>'],
['Operating system','Amazon Linux 2023'],
['<code>Amazon.Lambda.Core</code>','2.8.0'],
['<code>Amazon.Lambda.RuntimeSupport</code>','1.14.1'],
['<code>Amazon.Lambda.Serialization.SystemTextJson</code>','2.4.4'],
['<code>Amazon.Lambda.Tools</code> and <code>Amazon.Lambda.Templates</code>','6.0.0 and 8.0.1'],
['New with this runtime','C# file-based apps as functions, and support for Lambda Managed Instances']]),
p(`File-based apps and Managed Instances are outside this article. The subject here is the choice every existing function faces: how it is compiled and which runtime starts it.`),
h2('Architecture: three packages and what each hands to AWS'),
p(`A Lambda function for .NET is a package and a runtime setting. The package is either a set of assemblies or one native executable. The runtime is either the managed one, where AWS supplies .NET and keeps it patched, or the OS-only one, where the package brings everything it needs. SnapStart is a setting on top of the managed runtime.`),
window.IM('1','One project, three publish settings. The Native AOT executable runs on either runtime; the dashed line is the less usual pairing.'),
G.table(['Option','Advantages','Disadvantages and risks','Cost and operations'],[
['Managed runtime, JIT','Every library works. Smallest package. AWS patches .NET','Slowest start: the runtime loads and compiles on the first request','No extra charge. Nothing new to operate'],
['Managed runtime with ReadyToRun','Same compatibility. Some start-up compilation is done at build time','A modest gain. Package is larger, and tied to one architecture','No extra charge. One build property'],
['Managed runtime with SnapStart','Start-up work is done once, at publish. Same code and libraries','State captured in a snapshot must be made unique or fresh again after restore. Not with provisioned concurrency, Amazon EFS or more than 512 MB of ephemeral storage','For .NET, a charge to keep each snapshot and a charge per restore. Versions must be published, and old ones removed'],
['Native AOT','Fastest start and lowest memory. One file to deploy','No reflection-based serialisation, no run-time code generation. Each library must be trim-compatible. Build must target Amazon Linux 2023','No extra Lambda charge. You rebuild and redeploy to patch .NET. Longer builds']]),
p(`The rest of the article puts numbers and code behind that table.`),
h2('One function, one entry point'),
p(`The function prices a quote. It receives an API Gateway HTTP API event, looks up a product in a catalogue of 50,000 entries that it builds once at start-up, applies a tax rate and returns JSON. The catalogue stands in for the work a real function does once per execution environment: reading configuration, building lookup tables, creating clients.`),
snip('csharp','handler','    public APIGatewayHttpApiV2ProxyResponse Handle(','        return Respond(200, new QuoteResponse(quote.Sku, quote.Quantity, unitPrice, net, tax, net + tax, "EUR"));\n    }'),
p(`All three packages share one <code>Program.cs</code>. It is an executable assembly: the program creates the handler, registers two SnapStart hooks and hands control to the Lambda runtime client. On the managed runtime the function's handler setting is the assembly name, <code>Quotes.Function</code>. As Native AOT the same program is compiled to a file named <code>bootstrap</code>.`),
snip('csharp','program','QuoteHandler handler = new();','    .RunAsync();'),
p(`The difference between the builds is three property groups in the project file.`),
snip('xml','csproj','  <PropertyGroup Condition="\'$(Flavour)\' == \'r2r\'">','    <StripSymbols>true</StripSymbols>\n  </PropertyGroup>')
];
G.save(1,parts)
