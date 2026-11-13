eval(localStorage.art_H); const G=window.G,p=G.p,h2=G.h2; const snip=window.snip;
const RUN='https://github.com/nithinmohantk/blog-samples-working-repo/actions/runs/43464538846';
const REPO='https://github.com/nithinmohantk/blog-samples-working-repo/tree/main/dotnet10-on-lambda';
const parts=[
h2('Cost'),
p(`Lambda has billed the initialisation phase for every function since August 2025, so a slow start is paid for as well as waited for. The amounts are small. The figures below use the US East (N. Virginia) list prices for x86: $0.0000166667 per GB-second of duration, and for SnapStart on .NET $0.0000015046 per GB-second to keep a snapshot and $0.0001397998 per GB restored. The durations are the emulator's first-request times at the small CPU share, used only to show the proportions.`),
G.table(['For a 512 MB function','Sum','Result'],[
['One managed-runtime start, 0.871 s','0.871 &times; 0.5 GB &times; $0.0000166667','$0.0000073'],
['One Native AOT start, 0.099 s','0.099 &times; 0.5 GB &times; $0.0000166667','$0.0000008'],
['One SnapStart restore','0.5 GB &times; $0.0001397998','$0.0000699'],
['Keeping one SnapStart version for 30 days','0.5 GB &times; 2,592,000 s &times; $0.0000015046','$1.95'],
['A million cold starts a month, managed','','$7.26'],
['A million cold starts a month, Native AOT','','$0.83'],
['A million restores a month, plus the snapshot','','$71.85']]),
p(`Two things follow. First, none of these is a reason to choose on cost alone: a million cold starts a month is a busy function, and the whole range is under a hundred dollars. Second, for .NET SnapStart is something you pay for to buy latency. One restore costs the same as 8.4 seconds of billed duration at the same memory size, so it only saves money on a function whose initialisation is longer than that. Every published version with SnapStart enabled is charged for its snapshot until it is deleted, with a three-hour minimum, so the pipeline that publishes versions needs a step that removes old ones.`),
h2('Decision framework'),
G.mer(G.MF+`
flowchart TD
    A["A .NET 10 function on Lambda"] --> B{"Is the cold start<br/>a problem users notice?"}
    B -- "no" --> M["Managed runtime.<br/>Add ReadyToRun if it is free"]
    B -- "yes" --> C{"Do all dependencies build<br/>without trim warnings?"}
    C -- "yes" --> N["Native AOT, with the<br/>emulator test in the pipeline"]
    C -- "no" --> D{"Needs provisioned concurrency,<br/>EFS or large ephemeral storage?"}
    D -- "no" --> S["Managed runtime with SnapStart,<br/>hooks for unique and stale state"]
    D -- "yes" --> P["Managed runtime with<br/>provisioned concurrency"]
    style M fill:#FFF3E0,stroke:#FF9900,stroke-width:2px,color:#232F3E
    style N fill:#F0FFF4,stroke:#1D8102,stroke-width:2px,color:#145202
    style S fill:#EBF8FF,stroke:#0073BB,stroke-width:2px,color:#004C74
    style P fill:#F3E8FF,stroke:#7C3AED,stroke-width:2px,color:#4C1D95`),
G.table(['Situation','Choose','Reason'],[
['Queue consumers, scheduled jobs, internal APIs with tolerant callers','Managed runtime','Nobody is waiting on the first request. Keep full library compatibility and let AWS patch .NET'],
['A new, small function on an interactive path','Native AOT','Easiest when designed for it from the first commit: source-generated JSON, few dependencies'],
['An existing service with Entity Framework, reflection-heavy libraries or dynamic loading','SnapStart','The code stays as it is. The work moves to the hooks and to version management'],
['Strict latency with steady traffic','Provisioned concurrency','Environments are kept initialised. Costs more, and excludes SnapStart'],
['A team that cannot commit to rebuilding on every .NET security release','Managed runtime, with or without SnapStart','Native AOT moves that duty from AWS to you']]),
h2('Key takeaways'),
G.ul([
`The same source built three ways gave byte-identical answers to six events in the Lambda base images. The first request to a new environment took 254 ms on the managed runtime, 218 ms with ReadyToRun and 30 ms as Native AOT with a whole CPU, and 871, 792 and 99 ms with the CPU share of a 512 MB function.`,
`Native AOT is decided by serialisation and dependencies. A reflection-based JSON call produced compiler warnings, built anyway, and failed on its first request. Fail the build on <code>IL2026</code> and <code>IL3050</code>.`,
`Build Native AOT on Amazon Linux 2023. The executable runs on <code>provided.al2023</code> and also on <code>dotnet10</code>, whose start-up script hands over to a native file named by the handler setting.`,
`SnapStart keeps the code and libraries as they are, and asks for two hooks: do the expensive work before the snapshot, and renew everything unique or perishable after each restore. For .NET it has its own charges, and a restore costs as much as 8.4 seconds of duration.`,
`Put the emulator test in the pipeline with dated image tags. It runs the real runtime client against real event shapes in a few minutes and needs no AWS account.`]),
p(`If you have Init Duration figures from Lambda itself for the same function built as managed, SnapStart and Native AOT, I would like to see how they compare with the proportions here. Leave a comment.`),
G.callout('note','HOW THIS WAS CHECKED',`Everything shown ran in GitHub Actions on a hosted Linux runner with four vCPUs. The five builds were published inside an Amazon Linux 2023 container with .NET SDK 10.0.201 and clang 15. They ran in <code>public.ecr.aws/lambda/dotnet:10.2026.04.10.09</code>, which contains runtime 10.0.5, and <code>public.ecr.aws/lambda/provided:al2023.2026.04.10.07</code>, each started with 512 MB of memory and either one CPU or 0.29 of one. The handler's ten checks passed, all four configurations returned identical bodies and status codes for six events, and the reflection build behaved as described. Timings are medians of seven container starts and 203 warm requests per configuration, taken once; the Native AOT figure at 0.29 of a CPU varied most between starts. Not run: any deployment to Lambda, SnapStart snapshots and restores, the two hooks under the real runtime, arm64, container-image packaging, and any function with AWS SDK calls. The prices are list prices read from the AWS pricing page, not a bill. <a href="${RUN}" target="_blank" rel="noopener">The run is here</a>.`),
G.callout('tip','GET THE CODE',`The function, its checks, the build script for Amazon Linux 2023, the image-tag picker and the emulator test are in <a href="${REPO}" target="_blank" rel="noopener">dotnet10-on-lambda</a> in the samples repository. <code>./ci.sh out</code> runs all of it with Docker and Python 3.`).replace('class="callout callout-tip"','class="callout callout-tip sample-code-link"'),
h2('Glossary'),
G.box([
G.term('Managed runtime','A Lambda runtime in which AWS supplies and patches the language runtime, here dotnet10.'),
G.term('OS-only runtime','A Lambda runtime with an operating system and nothing else, here provided.al2023. The package must contain an executable named bootstrap.'),
G.term('Cold start','The first request to a new execution environment, which waits for the environment to be created and the function to initialise.'),
G.term('JIT','Just-in-time compilation: .NET turns intermediate code into machine code the first time each method runs.'),
G.term('ReadyToRun','Assemblies that carry precompiled machine code beside the intermediate code. The JIT is still present and still used.'),
G.term('Native AOT','Ahead-of-time compilation of the whole program to one native executable with no JIT.'),
G.term('Trimming','Removing code the compiler cannot see being used. Reflection hides uses from it.'),
G.term('Source generation','Code written by the compiler at build time, here the JSON serialisers for the listed types.'),
G.term('SnapStart','A Lambda feature that initialises a published version once, snapshots it, and starts environments by restoring the snapshot.'),
G.term('Runtime hook','Code a function registers to run before a SnapStart snapshot is taken or after one is restored.'),
G.term('Runtime Interface Emulator','A local stand-in for the Lambda service that passes HTTP invocations to a function through the Runtime API.'),
G.term('Provisioned concurrency','A Lambda setting that keeps a chosen number of execution environments initialised.')]),
h2('References &amp; Further Reading'),
G.box([
G.ref('https://aws.amazon.com/blogs/compute/net-10-runtime-now-available-in-aws-lambda/','.NET 10 runtime now available in AWS Lambda','AWS Compute Blog: the launch, package versions and new features'),
G.ref('https://aws.amazon.com/about-aws/whats-new/2026/01/aws-lambda-dot-net-10/','AWS Lambda adds support for .NET 10','The release announcement'),
G.ref('https://docs.aws.amazon.com/lambda/latest/dg/snapstart.html','Lambda SnapStart','Supported runtimes, limitations and pricing rules'),
G.ref('https://docs.aws.amazon.com/lambda/latest/dg/snapstart-runtime-hooks-dotnet.html','SnapStart runtime hooks for .NET','The registration API and its time limits'),
G.ref('https://docs.aws.amazon.com/lambda/latest/dg/dotnet-native-aot.html','Compile .NET Lambda function code to a native runtime format','AWS guidance on Native AOT, trimming and serialisation'),
G.ref('https://docs.aws.amazon.com/lambda/latest/dg/images-test.html','Testing Lambda container images locally','The Runtime Interface Emulator and the invocation endpoint'),
G.ref('https://gallery.ecr.aws/lambda/dotnet','AWS Lambda base images for .NET','The image and its dated tags'),
G.ref('https://github.com/aws/aws-lambda-dotnet','aws/aws-lambda-dotnet','The Lambda runtime client, serialisers and tools for .NET'),
G.ref('https://learn.microsoft.com/dotnet/core/deploying/native-aot/','Native AOT deployment','Microsoft: requirements and limitations'),
G.ref('https://learn.microsoft.com/dotnet/standard/serialization/system-text-json/source-generation','System.Text.Json source generation','Microsoft: contexts and options'),
G.ref('https://aws.amazon.com/blogs/compute/aws-lambda-standardizes-billing-for-init-phase/','AWS Lambda standardizes billing for INIT phase','AWS Compute Blog: initialisation is billed from August 2025'),
G.ref('https://aws.amazon.com/lambda/pricing/','AWS Lambda pricing','Duration, request and SnapStart prices'),
G.ref(REPO,'Sample code for this article','Function, build script, emulator test and results')])
];
G.save(4,parts)
