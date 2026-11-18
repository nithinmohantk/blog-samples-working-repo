// The same async code built twice: with compiler-generated state machines, and with Runtime Async.
// Prints the live stack inside a three-level async chain, and what the chain allocates.
// Usage: dotnet run -c Release [-p:RuntimeAsync=on] -- <label> <report.json>
using System.Diagnostics;
using System.Text.Json;
using System.Text.Json.Nodes;

string label = args.Length > 0 ? args[0] : "default";
(string[] before, string[] frames) = await Outer();
Console.WriteLine($"[{label}] {before.Length} frames in the live stack before the first suspension:");
foreach (string frame in before)
{
    Console.WriteLine("  " + frame);
}

Console.WriteLine($"[{label}] {frames.Length} frames in the live stack after resuming:");
foreach (string frame in frames)
{
    Console.WriteLine("  " + frame);
}

const int Iterations = 200_000;
for (int i = 0; i < 20_000; i++)
{
    await CompletedChain(i);
    await YieldingChain(i);
}

(double completedMs, double completedBytes) = await Run(CompletedChain);
(double yieldingMs, double yieldingBytes) = await Run(YieldingChain);
Console.WriteLine($"[{label}] chain that completes synchronously: {completedBytes:F0} bytes per call, {completedMs:F0} ms for {Iterations:N0} calls");
Console.WriteLine($"[{label}] chain that yields:                  {yieldingBytes:F0} bytes per call, {yieldingMs:F0} ms for {Iterations:N0} calls");

if (args.Length > 1)
{
    File.WriteAllText(args[1], new JsonObject
    {
        ["label"] = label,
        ["framesBeforeSuspension"] = new JsonArray([.. before.Select(f => (JsonNode)f)]),
        ["framesAfterResuming"] = new JsonArray([.. frames.Select(f => (JsonNode)f)]),
        ["completedChain"] = new JsonObject { ["bytesPerCall"] = Math.Round(completedBytes), ["ms"] = Math.Round(completedMs) },
        ["yieldingChain"] = new JsonObject { ["bytesPerCall"] = Math.Round(yieldingBytes), ["ms"] = Math.Round(yieldingMs) },
    }.ToJsonString(new JsonSerializerOptions { WriteIndented = true }));
}

return 0;

static async Task<(double Milliseconds, double BytesPerCall)> Run(Func<int, Task<int>> chain)
{
    long before = GC.GetTotalAllocatedBytes(precise: true);
    long started = Stopwatch.GetTimestamp();
    long total = 0;
    for (int i = 0; i < Iterations; i++)
    {
        total += await chain(i);
    }

    double elapsed = Stopwatch.GetElapsedTime(started).TotalMilliseconds;
    long allocated = GC.GetTotalAllocatedBytes(precise: true) - before;
    GC.KeepAlive(total);
    return (elapsed, (double)allocated / Iterations);
}

static async Task<(string[] Before, string[] After)> Outer() => await Middle();

static async Task<(string[] Before, string[] After)> Middle() => await Inner();

static async Task<(string[] Before, string[] After)> Inner()
{
    string[] before = LiveStack();
    await Task.Yield();
    return (before, LiveStack());
}

static string[] LiveStack() =>
    [.. new StackTrace(skipFrames: 1, fNeedFileInfo: false).GetFrames().Select(f => DiagnosticMethodInfo.Create(f) is { } m ? $"{m.DeclaringTypeName}.{m.Name}" : "?")];

static async Task<int> CompletedChain(int value) => await CompletedMiddle(value) + 1;

static async Task<int> CompletedMiddle(int value) => await CompletedInner(value) + 1;

static async Task<int> CompletedInner(int value)
{
    await Task.CompletedTask;
    return value;
}

static async Task<int> YieldingChain(int value) => await YieldingMiddle(value) + 1;

static async Task<int> YieldingMiddle(int value) => await YieldingInner(value) + 1;

static async Task<int> YieldingInner(int value)
{
    await Task.Yield();
    return value;
}
