// Exercises the .NET 11 library additions an architect is most likely to design around, on synthetic data,
// and writes what happened to a JSON report. Usage: dotnet run -c Release -- <report.json>
using System.Diagnostics;
using System.IO.Compression;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using Dotnet11Sample;

JsonObject report = new() { ["runtime"] = System.Runtime.InteropServices.RuntimeInformation.FrameworkDescription };
int failed = 0;

void Check(string name, bool condition)
{
    failed += condition ? 0 : 1;
    Console.WriteLine($"{(condition ? "ok  " : "FAIL")}  {name}");
}

// 1. Zstandard beside gzip and Brotli, on the same payload.
byte[] payload = Payload.JsonLines(3000);
JsonArray compression = [];
(string Name, Func<Stream, CompressionLevel, Stream> Compress, Func<Stream, Stream> Decompress)[] codecs =
[
    ("gzip", (s, level) => new GZipStream(s, level, leaveOpen: true), s => new GZipStream(s, CompressionMode.Decompress)),
    ("brotli", (s, level) => new BrotliStream(s, level, leaveOpen: true), s => new BrotliStream(s, CompressionMode.Decompress)),
    ("zstandard", (s, level) => new ZstandardStream(s, level, leaveOpen: true), s => new ZstandardStream(s, CompressionMode.Decompress)),
];
foreach ((string name, Func<Stream, CompressionLevel, Stream> compress, Func<Stream, Stream> decompress) in codecs)
{
    foreach (CompressionLevel level in new[] { CompressionLevel.Fastest, CompressionLevel.Optimal, CompressionLevel.SmallestSize })
    {
        byte[] Pack()
        {
            using MemoryStream target = new();
            using (Stream stream = compress(target, level))
            {
                stream.Write(payload);
            }

            return target.ToArray();
        }

        byte[] packed = Pack();
        byte[] Unpack()
        {
            using MemoryStream target = new();
            using (Stream stream = decompress(new MemoryStream(packed)))
            {
                stream.CopyTo(target);
            }

            return target.ToArray();
        }

        Check($"{name} {level}: round trip", Unpack().AsSpan().SequenceEqual(payload));
        compression.Add(new JsonObject
        {
            ["codec"] = name, ["level"] = level.ToString(), ["bytes"] = packed.Length,
            ["ratio"] = Math.Round((double)payload.Length / packed.Length, 2),
            ["compressMs"] = Measure.MedianMilliseconds(() => Pack()),
            ["decompressMs"] = Measure.MedianMilliseconds(() => Unpack()),
        });
    }
}

report["compression"] = new JsonObject { ["payloadBytes"] = payload.Length, ["rows"] = compression };

// 2. FullJoin: reconcile two sides and keep what is missing from either.
string[] source = ["obs-1", "obs-2", "obs-3", "obs-5"];
string[] target = ["obs-2", "obs-3", "obs-4"];
List<(string? Source, string? Target)> joined = [.. source.FullJoin(target, s => s, t => t, StringComparer.Ordinal)];
string[] onlyInSource = [.. joined.Where(j => j.Target is null).Select(j => j.Source!)];
string[] onlyInTarget = [.. joined.Where(j => j.Source is null).Select(j => j.Target!)];
Check("FullJoin: finds what is only in the source", onlyInSource.SequenceEqual(["obs-1", "obs-5"]));
Check("FullJoin: finds what is only in the target", onlyInTarget.SequenceEqual(["obs-4"]));
report["fullJoin"] = new JsonObject
{
    ["rows"] = joined.Count, ["matched"] = joined.Count(j => j.Source is not null && j.Target is not null),
    ["onlyInSource"] = new JsonArray([.. onlyInSource.Select(s => (JsonNode)s)]),
    ["onlyInTarget"] = new JsonArray([.. onlyInTarget.Select(s => (JsonNode)s)]),
};

// 3. JSON Lines from an async sequence, without buffering the whole set.
async IAsyncEnumerable<Payload.Reading> Stream(int count)
{
    foreach (Payload.Reading reading in Payload.Readings(count))
    {
        await Task.Yield();
        yield return reading;
    }
}

using MemoryStream lines = new();
await JsonSerializer.SerializeAsyncEnumerable(lines, Stream(100), topLevelValues: true, JsonSerializerOptions.Web, CancellationToken.None);
string[] written = Encoding.UTF8.GetString(lines.ToArray()).Split('\n', StringSplitOptions.RemoveEmptyEntries);
Check("JSON Lines: one document per line", written.Length == 100 && written.All(l => JsonNode.Parse(l)!["beatsPerMinute"] is not null));
report["jsonLines"] = new JsonObject { ["lines"] = written.Length, ["first"] = written[0] };

// 4. Run a process and capture its output in one call.
ProcessTextOutput version = await Process.RunAndCaptureTextAsync("dotnet", ["--version"], CancellationToken.None);
Check("Process: exit status and output captured", version.ExitStatus.ExitCode == 0 && version.StandardOutput.Trim().Length > 0);
report["process"] = new JsonObject { ["command"] = "dotnet --version", ["exitCode"] = version.ExitStatus.ExitCode, ["output"] = version.StandardOutput.Trim() };

// 5. Read a string as a stream without copying it into a byte array first.
string settings = """{"service":"coding","limits":{"requestsPerMinute":120}}""";
using StringStream settingsStream = new(settings, Encoding.UTF8);
using JsonDocument parsed = await JsonDocument.ParseAsync(settingsStream);
Check("StringStream: parsed as a stream", parsed.RootElement.GetProperty("limits").GetProperty("requestsPerMinute").GetInt32() == 120);
report["stringStream"] = new JsonObject { ["length"] = settingsStream.Length };

if (args.Length > 0)
{
    File.WriteAllText(args[0], report.ToJsonString(new JsonSerializerOptions { WriteIndented = true }));
}

Console.WriteLine(failed == 0 ? "\nAll checks passed" : $"\n{failed} check(s) failed");
return failed == 0 ? 0 : 1;
