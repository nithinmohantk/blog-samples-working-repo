using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using Desk.Core;

namespace Desk.AgentFramework;

/// <summary>
/// The mapped endpoint owns the event stream, so this reads it from outside: the request body on the
/// way in, the server-sent events on the way out. A test tool, like the wire log it fills.
/// </summary>
public sealed class WireTap(RequestDelegate next, WireLog log)
{
    private static readonly string[] s_kept = ["RUN_FINISHED", "STATE_SNAPSHOT", "RUN_ERROR"];

    public async Task InvokeAsync(HttpContext context)
    {
        if (!HttpMethods.IsPost(context.Request.Method) || !context.Request.Path.Equals("/agent"))
        {
            await next(context);
            return;
        }

        context.Request.EnableBuffering();
        JsonNode? request = null;
        try
        {
            request = await JsonNode.ParseAsync(context.Request.Body, cancellationToken: context.RequestAborted);
        }
        catch (JsonException)
        {
            // Not JSON: the endpoint will say so.
        }

        context.Request.Body.Position = 0;
        Stream original = context.Response.Body;
        Copy copy = new(original);
        context.Response.Body = copy;
        bool completed = false;
        try
        {
            await next(context);
            completed = !context.RequestAborted.IsCancellationRequested;
        }
        finally
        {
            context.Response.Body = original;
            if (request is not null && context.Response.ContentType?.StartsWith("text/event-stream", StringComparison.Ordinal) == true)
            {
                log.Add(Read(request, copy.Text, completed));
            }
        }
    }

    private static WireEntry Read(JsonNode request, string stream, bool completed)
    {
        List<string> types = [];
        List<JsonNode> payloads = [];
        foreach (string line in stream.Split('\n'))
        {
            if (!line.StartsWith("data:", StringComparison.Ordinal))
            {
                continue;
            }

            try
            {
                JsonNode? item = JsonNode.Parse(line.AsSpan(5).Trim().ToString());
                string type = item?["type"]?.GetValue<string>() ?? "?";
                types.Add(type);
                if (item is not null && s_kept.Contains(type))
                {
                    payloads.Add(item);
                }
            }
            catch (JsonException)
            {
                // A line cut short by a cancelled request.
            }
        }

        return new WireEntry(request, types, payloads, completed);
    }

    /// <summary>Passes every write through and keeps a copy.</summary>
    private sealed class Copy(Stream inner) : Stream
    {
        private readonly MemoryStream _kept = new();

        public string Text => Encoding.UTF8.GetString(_kept.GetBuffer(), 0, (int)_kept.Length);

        public override bool CanRead => false;
        public override bool CanSeek => false;
        public override bool CanWrite => true;
        public override long Length => throw new NotSupportedException();
        public override long Position { get => throw new NotSupportedException(); set => throw new NotSupportedException(); }

        public override void Flush() => inner.Flush();
        public override Task FlushAsync(CancellationToken cancellationToken) => inner.FlushAsync(cancellationToken);
        public override int Read(byte[] buffer, int offset, int count) => throw new NotSupportedException();
        public override long Seek(long offset, SeekOrigin origin) => throw new NotSupportedException();
        public override void SetLength(long value) => throw new NotSupportedException();

        public override void Write(byte[] buffer, int offset, int count)
        {
            _kept.Write(buffer, offset, count);
            inner.Write(buffer, offset, count);
        }

        public override ValueTask WriteAsync(ReadOnlyMemory<byte> buffer, CancellationToken cancellationToken = default)
        {
            _kept.Write(buffer.Span);
            return inner.WriteAsync(buffer, cancellationToken);
        }

        public override Task WriteAsync(byte[] buffer, int offset, int count, CancellationToken cancellationToken)
            => WriteAsync(buffer.AsMemory(offset, count), cancellationToken).AsTask();
    }
}
