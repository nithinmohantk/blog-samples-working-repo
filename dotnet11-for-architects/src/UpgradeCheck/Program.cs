// One program, built for net10.0 and net11.0, run on the same machine. It records behaviour that the
// .NET 11 release notes say has changed, and a few timings, so an upgrade is decided on evidence.
// Usage: dotnet run -c Release -f net11.0 -- <report.json>
using System.IO.Compression;
using System.Numerics;
using System.Runtime.InteropServices;
using System.Runtime.Intrinsics.X86;
using System.Text.Json;
using System.Text.Json.Nodes;
using Dotnet11Sample;

// Values arrive at run time so the compiler cannot fold the conversions below.
double big = double.Parse(Environment.GetEnvironmentVariable("UPGRADE_CHECK_BIG") ?? "300.7", System.Globalization.CultureInfo.InvariantCulture);
double negative = -big;
double huge = big * 1e9;

static int EmptyLength(Func<Stream, Stream> wrap)
{
    using MemoryStream target = new();
    wrap(target).Dispose();
    return target.ToArray().Length;
}

JsonObject behaviour = new()
{
    ["empty gzip stream, bytes written"] = EmptyLength(s => new GZipStream(s, CompressionLevel.Optimal, leaveOpen: true)),
    ["empty deflate stream, bytes written"] = EmptyLength(s => new DeflateStream(s, CompressionLevel.Optimal, leaveOpen: true)),
    ["empty zlib stream, bytes written"] = EmptyLength(s => new ZLibStream(s, CompressionLevel.Optimal, leaveOpen: true)),
    ["unchecked (byte)300.7"] = unchecked((byte)big),
    ["unchecked (sbyte)300.7"] = unchecked((sbyte)big),
    ["unchecked (byte)-300.7"] = unchecked((byte)negative),
    ["unchecked (short)300.7e9"] = unchecked((short)huge),
    ["unchecked (ushort)-300.7"] = unchecked((ushort)negative),
    ["unchecked (int)300.7e9"] = unchecked((int)huge),
    ["(double)BigInteger 2^53+1"] = ((double)(BigInteger.Pow(2, 53) + 1)).ToString("R", System.Globalization.CultureInfo.InvariantCulture),
    ["(decimal)BigInteger 10^28+5 / 10"] = ((decimal)(BigInteger.Pow(10, 28) + 5) / 10m).ToString(System.Globalization.CultureInfo.InvariantCulture),
    ["(BigInteger)2.5m"] = ((BigInteger)2.5m).ToString(),
    ["(BigInteger)-2.5m"] = ((BigInteger)(-2.5m)).ToString(),
    ["(decimal)0.1f"] = ((decimal)0.1f).ToString(System.Globalization.CultureInfo.InvariantCulture),
    ["(decimal)1e-7d * 3"] = ((decimal)(1e-7 * 3)).ToString(System.Globalization.CultureInfo.InvariantCulture),
};

JsonObject cpu = new()
{
    ["architecture"] = RuntimeInformation.ProcessArchitecture.ToString(),
    ["x86-64-v2: SSE4.2"] = Sse42.IsSupported, ["x86-64-v2: POPCNT"] = Popcnt.IsSupported, ["x86-64-v2: SSSE3"] = Ssse3.IsSupported,
    ["x86-64-v3: AVX2"] = Avx2.IsSupported, ["x86-64-v3: BMI2"] = Bmi2.IsSupported, ["x86-64-v3: FMA"] = Fma.IsSupported,
    ["x86-64-v3: LZCNT"] = Lzcnt.IsSupported,
};

byte[] payload = Payload.JsonLines(3000);
string[] lines = System.Text.Encoding.UTF8.GetString(payload).Split('\n', StringSplitOptions.RemoveEmptyEntries);
IReadOnlyList<Payload.Reading> readings = Payload.Readings(3000);

static async Task<int> Leaf(int value)
{
    await Task.CompletedTask;
    return value + 1;
}

static async Task<int> Chain(int value) => await Leaf(value) + await Leaf(value);

JsonObject timings = new()
{
    ["parse 3,000 JSON documents"] = Measure.MedianMilliseconds(() =>
    {
        long sum = 0;
        foreach (string line in lines)
        {
            using JsonDocument document = JsonDocument.Parse(line);
            sum += document.RootElement.GetProperty("valueQuantity").GetProperty("value").GetInt32();
        }

        GC.KeepAlive(sum);
    }),
    ["serialize 3,000 records"] = Measure.MedianMilliseconds(() => GC.KeepAlive(JsonSerializer.SerializeToUtf8Bytes(readings))),
    ["gzip Optimal, 1 MB of JSON Lines"] = Measure.MedianMilliseconds(() =>
    {
        using MemoryStream target = new();
        using (GZipStream stream = new(target, CompressionLevel.Optimal, leaveOpen: true))
        {
            stream.Write(payload);
        }
    }),
    ["group and average by patient"] = Measure.MedianMilliseconds(() =>
        GC.KeepAlive(readings.GroupBy(r => r.Patient).Select(g => (g.Key, g.Average(r => r.BeatsPerMinute))).OrderBy(x => x.Key).ToList())),
    ["500,000 awaits of completed tasks"] = Measure.MedianMilliseconds(() =>
    {
        long sum = 0;
        for (int i = 0; i < 250_000; i++)
        {
            sum += Chain(i).GetAwaiter().GetResult();
        }

        GC.KeepAlive(sum);
    }),
};

JsonObject report = new()
{
    ["runtime"] = RuntimeInformation.FrameworkDescription, ["os"] = RuntimeInformation.OSDescription,
    ["behaviour"] = behaviour, ["cpu"] = cpu, ["timingsMs"] = timings,
};
string json = report.ToJsonString(new JsonSerializerOptions { WriteIndented = true });
Console.WriteLine(json);
if (args.Length > 0)
{
    File.WriteAllText(args[0], json);
}
