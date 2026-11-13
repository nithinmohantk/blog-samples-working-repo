eval(localStorage.art_H); const G=window.G,p=G.p,h2=G.h2; const snip=window.snip;
const parts=[
h2('What the emulator measured'),
p(`The emulator starts the function's process when the first invocation arrives, so the first request to a new container pays for runtime start-up, for building the catalogue and for the first pass through the handler. The test started seven containers per configuration and then sent warm requests. Lambda gives a function CPU in proportion to its memory, one vCPU at 1,769 MB, so a 512 MB function has about 0.29 of one. The test ran once with a whole CPU and once with that share.`),
snip('text','r_emu','== 1 CPU: first request','Native AOT, managed runtime                    299 ms          104 ms         101 ms   1.24 ms   71.6 ms   22 MiB'),
window.IM('2','First-request time by build. The gap between the managed runtime and Native AOT widens when the CPU share is small.'),
p(`Four observations, each limited to what was run.`),
G.ul([
`<strong>The JIT is most of the first request.</strong> With a whole CPU the managed build took 254 ms and Native AOT 30 ms. With 0.29 of a CPU the managed build took 871 ms. Native AOT took 99 ms at the median, and between 40 and 110 ms across the seven starts, so its figure at the small share is the less stable of the two.`,
`<strong>ReadyToRun helped by about a tenth.</strong> 218 ms against 254, and 792 against 871. The runtime still has to load, and the Lambda runtime client and its start-up path are the same.`,
`<strong>The runtime Native AOT runs on barely matters.</strong> Going through the managed runtime's start-up script cost 9 ms with a whole CPU and 5 ms at the smaller share, which is inside the spread.`,
`<strong>Warm requests are the same.</strong> 1.2 to 1.4 ms through the emulator's HTTP interface for every build. The 70 to 80 ms at the 99th percentile under 0.29 of a CPU appears equally in all four configurations, which points at the container being paused by its CPU quota and not at the code.`]),
p(`Memory, as Docker reports it for the whole container after 30 requests, was 32 MiB for the managed builds and 22 MiB for Native AOT.`),
G.callout('warning','WHAT THESE NUMBERS ARE NOT',`They are not Lambda cold starts. A real cold start also creates the execution environment, downloads the package, and on a real function opens network connections and creates SDK clients. All of that is missing here and all of it adds time to every build. What carries over is the direction and rough size of the difference between builds of the same code, and that Docker's CPU limit is a stand-in for Lambda's allocation, not a copy of it. Measure on Lambda before you set a latency target.`),
h2('SnapStart: the rules, and the code that has to follow them'),
p(`SnapStart changes when initialisation happens. When a function version is published, Lambda initialises it once, takes a snapshot of the memory and disk of that execution environment, and starts later environments by restoring the snapshot. For .NET it is available on the managed runtimes from .NET 8 onward, and only for published versions and the aliases that point at them, never for <code>$LATEST</code>. It cannot be combined with provisioned concurrency, Amazon EFS or ephemeral storage above 512 MB. OS-only runtimes are not supported.`),
p(`Two consequences follow for the code. Whatever the function did before the snapshot is shared by every environment restored from it. And whatever it did not do before the snapshot is still paid for on the first request after a restore. The runtime offers a hook for each: one that runs before the snapshot is taken, one that runs after every restore. They are the two registrations in <code>Program.cs</code> above, and these are the methods they call.`),
snip('csharp','handler','    /// <summary>Runs the whole request path once','        Handled = 0;\n    }'),
p(`<code>Warm</code> sends one request through the handler before the snapshot, so the JSON code and the handler have been compiled and are part of what is restored. <code>BecomeANewInstance</code> reissues everything that must differ between two environments. In this function that is one identifier. In a real one the list is longer.`),
G.table(['State captured in a snapshot','What goes wrong','What to do after restore'],[
['Identifiers and random seeds created at start-up','Two environments issue the same "unique" value','Create them again. Prefer creating them per request'],
['Network connections','The socket in the snapshot is dead by the time it is restored','Reconnect, or connect lazily on first use'],
['Credentials and tokens fetched at start-up','They have expired, or are shared more widely than intended','Fetch after restore, and honour their expiry'],
['Cached configuration and timestamps','The function serves values from the day the version was published','Refresh, or cache with a lifetime']]),
p(`The two methods are covered by the sample's own checks, which run without any Lambda runtime:`),
snip('text','r_self','ok    warming runs a request','ok    after a restore the instance has a new identity and a clean count'),
p(`That is as far as local testing goes. The emulator has no snapshot, so neither hook is called in it, and nothing here measures what SnapStart saves. AWS documents two limits to design for: after a restore, the runtime and the after-restore hooks together have ten seconds, and the registration API needs <code>Amazon.Lambda.Core</code> 2.5.0 or later.`),
G.callout('note','NATIVE AOT WITH SNAPSTART',`The SnapStart documentation excludes OS-only runtimes. It does not say what happens to a Native AOT executable deployed on the <code>dotnet10</code> runtime, and that combination was not tested here. Treat it as requiring clarification from AWS before planning on it. With a first request of tens of milliseconds, there is also little left for a snapshot to remove.`),
h2('Security and operations'),
G.table(['Concern','Managed runtime, with or without SnapStart','Native AOT'],[
['Patching .NET','AWS updates the runtime. With SnapStart, Lambda re-runs initialisation to apply the update, which is billed','.NET is inside your executable. A security release means a rebuild and a redeploy of every function'],
['What you must track','Runtime deprecation dates','.NET patch releases, and the SDK version in the build image'],
['Secrets','Never read a secret before a snapshot unless it is re-read after restore','No snapshot. Read at start-up as usual'],
['Diagnostics','Full stack traces. Any profiler or agent that works on .NET','Stack traces keep method names, as the failure above shows. Tools that depend on the JIT or on run-time instrumentation do not work'],
['Cold-start visibility','The <code>Init Duration</code> and, with SnapStart, <code>Restore Duration</code> fields of the REPORT log line','<code>Init Duration</code>'],
['Pipeline','Build anywhere. Publish a version and move an alias','Build on Amazon Linux 2023 for the target architecture. Fail on trim warnings. Run the executable against recorded events before deploying']]),
p(`Whichever option is chosen, the test in this article belongs in the pipeline. It needs Docker and nothing else, takes a few minutes for five builds and four configurations, and it catches the two failures that otherwise appear only after deployment: a package the runtime cannot start, and a Native AOT build that has lost a code path.`)
];
G.save(3,parts)
